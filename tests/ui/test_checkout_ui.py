"""Browser tests of the checkout page with Playwright (REQ-UI-*)."""
import pytest
from playwright.sync_api import Page, expect, sync_playwright

pytestmark = pytest.mark.ui


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


# Puppeteer's "Fast 3G" preset (aligned with Chrome DevTools): 562.5 ms round trip, about 1.44 Mbit/s down, 0.68 up.
FAST_3G = {"offline": False, "latency": 150 * 3.75, "downloadThroughput": 1.6e6 / 8 * 0.9, "uploadThroughput": 750e3 / 8 * 0.9}
PHONE_WIDTH = 360


def _open(browser, base_url, request, screenshots, phone=False):
    context = (browser.new_context(viewport={"width": PHONE_WIDTH, "height": 740}, is_mobile=True, has_touch=True) if phone
               else browser.new_context(viewport={"width": 900, "height": 900}))
    page = context.new_page()
    if phone:
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", FAST_3G)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})  # a budget phone's CPU
        page.network = cdp  # this session's conditions win over later ones, so TC-UI-011 goes offline through it
    page.goto(base_url)
    expect(page.get_by_test_id("product-NB-A5")).to_be_visible(timeout=20_000)
    yield page
    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        page.screenshot(path=str(screenshots / f"FAILED-{request.node.name}.png"), full_page=True)
    context.close()


@pytest.fixture()
def page(browser, base_url, api, request, screenshots):
    yield from _open(browser, base_url, request, screenshots)


@pytest.fixture()
def phone(browser, base_url, api, request, screenshots):
    """A 360 px touch phone on a throttled 3G connection with a 4x slower CPU."""
    yield from _open(browser, base_url, request, screenshots, phone=True)


def fill_and_place(page: Page, qty: dict[str, int], email="qa@example.com", coupon=""):
    for sku, n in qty.items():
        page.get_by_test_id(f"qty-{sku}").fill(str(n))
    page.get_by_test_id("email-input").fill(email)
    page.get_by_test_id("coupon-input").fill(coupon)
    page.get_by_test_id("place-order").click()


def test_tc_ui_001_catalogue_shows_every_product_with_stock(page, api):
    """TC-UI-001: the page lists every product from the API with its stock level."""
    products = api.get("/api/products").json()
    for p in products:
        expect(page.get_by_test_id(f"stock-{p['sku']}")).to_have_text(str(p["stock"]))
    expect(page.locator("#products tr")).to_have_count(len(products))


def test_tc_ui_002_place_order_shows_correct_summary(page, screenshots):
    """TC-UI-002: placing 2 x Notebook shows subtotal 240.00, shipping 40.00 and total 280.00."""
    fill_and_place(page, {"NB-A5": 2})
    expect(page.get_by_test_id("order-status")).to_have_text("PLACED")
    expect(page.get_by_test_id("summary-subtotal")).to_have_text("Rs 240.00")
    expect(page.get_by_test_id("summary-shipping")).to_have_text("Rs 40.00")
    expect(page.get_by_test_id("summary-total")).to_have_text("Rs 280.00")
    page.screenshot(path=str(screenshots / "evidence-checkout-happy-path.png"), full_page=True)


def test_tc_ui_003_coupon_discount_is_reflected_in_the_total(page):
    """TC-UI-003: FLAT50 on Rs 300.00 -> discount 50.00 and displayed total 290.00 (matches the API)."""
    fill_and_place(page, {"BND-B": 1, "BND-D": 1}, coupon="FLAT50")
    expect(page.get_by_test_id("summary-discount")).to_have_text("-Rs 50.00")
    expect(page.get_by_test_id("summary-total")).to_have_text("Rs 290.00")


def test_tc_ui_004_invalid_email_shows_an_error_and_no_summary(page):
    """TC-UI-004: an invalid e-mail shows the server's message and no order summary."""
    fill_and_place(page, {"NB-A5": 1}, email="not-an-email")
    expect(page.get_by_test_id("error-message")).to_have_text("invalid customer_email")
    expect(page.get_by_test_id("order-summary")).to_be_hidden()


def test_tc_ui_005_stock_on_screen_drops_after_an_order(page):
    """TC-UI-005: the stock column refreshes after an order (50 -> 47)."""
    fill_and_place(page, {"NB-A5": 3})
    expect(page.get_by_test_id("order-status")).to_have_text("PLACED")
    expect(page.get_by_test_id("stock-NB-A5")).to_have_text("47")


def test_tc_ui_006_cancelling_in_the_browser_restores_the_stock_shown(page):
    """TC-UI-006: Cancel order sets status CANCELLED and the stock column returns to 50."""
    fill_and_place(page, {"NB-A5": 3})
    page.get_by_test_id("cancel-order").click()
    expect(page.get_by_test_id("order-status")).to_have_text("CANCELLED")
    expect(page.get_by_test_id("stock-NB-A5")).to_have_text("50")


def test_tc_ui_007_cancel_after_shipping_is_blocked_with_a_message(page, api):
    """TC-UI-007: an order that has shipped cannot be cancelled from the page; the error is shown."""
    fill_and_place(page, {"NB-A5": 1})
    expect(page.get_by_test_id("order-status")).to_have_text("PLACED")  # wait for the order to render before reading its id
    oid = int(page.get_by_test_id("order-id").text_content().lstrip("#"))
    api.post(f"/api/orders/{oid}/pay")
    api.post(f"/api/orders/{oid}/ship")
    page.get_by_test_id("cancel-order").click()
    expect(page.get_by_test_id("error-message")).to_contain_text("cannot cancel an order that is SHIPPED")
    expect(page.get_by_test_id("order-status")).not_to_have_text("CANCELLED")


def test_tc_ui_008_mobile_checkout_on_3g(phone, api):
    """TC-UI-008: on a 360 px phone over 3G, the totals fit the screen, UPI shows PENDING then SUCCESS, and a double tap on Pay starts one payment."""
    fill_and_place(phone, {"NB-A5": 2})
    expect(phone.get_by_test_id("order-status")).to_have_text("PLACED", timeout=20_000)
    assert phone.evaluate("document.documentElement.scrollWidth") <= PHONE_WIDTH  # no sideways scrolling
    total = phone.get_by_test_id("summary-total").bounding_box()
    assert total["x"] + total["width"] <= PHONE_WIDTH
    phone.get_by_test_id("upi-input").fill("success@sandbox")
    pay = phone.get_by_test_id("pay-upi")
    pay.scroll_into_view_if_needed()
    box = pay.bounding_box()
    for _ in range(2):  # an impatient double tap while the first request is still travelling over 3G
        phone.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(phone.get_by_test_id("payment-status")).to_have_text("PENDING", timeout=20_000)
    expect(phone.get_by_test_id("payment-status")).to_have_text("SUCCESS", timeout=20_000)
    expect(phone.get_by_test_id("order-status")).to_have_text("PAID", timeout=20_000)
    expect(phone.get_by_test_id("error-message")).to_have_text("")
    oid = int(phone.get_by_test_id("order-id").text_content().lstrip("#"))
    assert len(api.get(f"/api/orders/{oid}/payments").json()) == 1


def test_tc_ui_009_declined_upi_payment_shows_the_reason_and_a_retry_pays(page):
    """TC-UI-009: a Z9 decline shows its reason and keeps the order PLACED; paying again with another UPI ID marks it PAID."""
    fill_and_place(page, {"NB-A5": 1})
    expect(page.get_by_test_id("order-status")).to_have_text("PLACED")
    page.get_by_test_id("upi-input").fill("z9@sandbox")
    page.get_by_test_id("pay-upi").click()
    expect(page.get_by_test_id("payment-status")).to_have_text("FAILED", timeout=10_000)
    expect(page.get_by_test_id("payment-message")).to_have_text("Not enough money in the account (Z9).")
    expect(page.get_by_test_id("order-status")).to_have_text("PLACED")
    page.get_by_test_id("upi-input").fill("success@sandbox")
    page.get_by_test_id("pay-upi").click()
    expect(page.get_by_test_id("order-status")).to_have_text("PAID", timeout=10_000)


WAITING = "Still waiting for your bank. Don't pay again: this page keeps checking, and you won't be charged twice."
OFFLINE = "No connection. This page keeps checking the same payment and won't start a new one."


def test_tc_ui_010_a_slow_bank_gets_a_clear_message_and_no_second_payment(page, api):
    """TC-UI-010: when the bank has not answered after a minute, the page says so, keeps checking the same payment and keeps Pay disabled."""
    page.clock.install()  # fake timers, so a minute of status checks takes a few seconds
    page.reload()
    fill_and_place(page, {"NB-A5": 1})
    expect(page.get_by_test_id("order-status")).to_have_text("PLACED")
    page.get_by_test_id("upi-input").fill("pending@sandbox")
    page.get_by_test_id("pay-upi").click()
    expect(page.get_by_test_id("payment-status")).to_have_text("PENDING")
    message = page.get_by_test_id("payment-message")
    for _ in range(150):  # each step fires the next status check once its timer is set; a step with none is harmless
        page.clock.run_for(1500)
        page.wait_for_timeout(30)
        if message.text_content() == WAITING:
            break
    expect(message).to_have_text(WAITING)
    expect(page.get_by_test_id("pay-upi")).to_be_disabled()
    with page.expect_response("**/api/payments/*"):
        page.clock.run_for(15_000)  # it keeps checking, every 15 s
    oid = int(page.get_by_test_id("order-id").text_content().lstrip("#"))
    assert [p["status"] for p in api.get(f"/api/orders/{oid}/payments").json()] == ["PENDING"]


def test_tc_ui_011_phone_offline_during_payment_keeps_the_same_payment(phone, api):
    """TC-UI-011: a phone that loses its connection while a payment is pending says so, and once back online settles that same payment."""
    fill_and_place(phone, {"NB-A5": 1})
    expect(phone.get_by_test_id("order-status")).to_have_text("PLACED", timeout=20_000)
    phone.get_by_test_id("upi-input").fill("success@sandbox")
    phone.get_by_test_id("pay-upi").click()
    expect(phone.get_by_test_id("payment-status")).to_have_text("PENDING", timeout=20_000)
    phone.network.send("Network.emulateNetworkConditions", {**FAST_3G, "offline": True})  # before the first check
    expect(phone.get_by_test_id("payment-message")).to_have_text(OFFLINE, timeout=20_000)
    phone.network.send("Network.emulateNetworkConditions", FAST_3G)
    expect(phone.get_by_test_id("payment-status")).to_have_text("SUCCESS", timeout=20_000)
    expect(phone.get_by_test_id("order-status")).to_have_text("PAID", timeout=20_000)
    oid = int(phone.get_by_test_id("order-id").text_content().lstrip("#"))
    assert len(api.get(f"/api/orders/{oid}/payments").json()) == 1
