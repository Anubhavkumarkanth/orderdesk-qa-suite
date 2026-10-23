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


@pytest.fixture()
def page(browser, base_url, api, request, screenshots):
    context = browser.new_context(viewport={"width": 900, "height": 900})
    page = context.new_page()
    page.goto(base_url)
    expect(page.get_by_test_id("product-NB-A5")).to_be_visible()
    yield page
    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        page.screenshot(path=str(screenshots / f"FAILED-{request.node.name}.png"), full_page=True)
    context.close()


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
