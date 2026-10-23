# Defect detection matrix

Each row runs the full suite (86 tests) with only that defect switched on.

| Defect | Tests failing | Caught by |
|---|---:|---|
| none (clean build) | 0 | all 86 tests pass |
| BUG-001 | 1 | `api/test_pricing_boundaries::test_tc_qty_001_quantity_boundaries[11-422]` |
| BUG-002 | 3 | `api/test_pricing_boundaries::test_tc_prc_001_save10_minimum_subtotal_boundary[items1-201]`<br>`api/test_pricing_boundaries::test_tc_prc_002_save10_at_exact_minimum_gives_free_shipping_and_correct_total`<br>`api/test_pricing_boundaries::test_tc_prc_008_total_identity_holds_for_every_coupon_case` |
| BUG-003 | 1 | `api/test_pricing_boundaries::test_tc_prc_002_save10_at_exact_minimum_gives_free_shipping_and_correct_total` |
| BUG-004 | 5 | `api/test_order_lifecycle::test_tc_lif_004_cancel_restores_stock[PLACED]`<br>`api/test_order_lifecycle::test_tc_lif_004_cancel_restores_stock[PAID]`<br>`api/test_order_lifecycle::test_tc_lif_005_cancel_restores_every_line_of_a_multi_line_order`<br>`db/test_db_integrity::test_tc_dat_003_stock_is_conserved`<br>`ui/test_checkout_ui::test_tc_ui_006_cancelling_in_the_browser_restores_the_stock_shown` |
| BUG-005 | 2 | `api/test_order_lifecycle::test_tc_lif_003_cancel_is_only_allowed_before_shipping[SHIPPED]`<br>`ui/test_checkout_ui::test_tc_ui_007_cancel_after_shipping_is_blocked_with_a_message` |
| BUG-006 | 1 | `api/test_orders_api::test_tc_val_001_invalid_email_is_rejected[user@nodot]` |
| BUG-007 | 1 | `api/test_pricing_boundaries::test_tc_prc_003_percentage_discount_rounds_half_up[items1-5001]` |
| BUG-008 | 1 | `ui/test_checkout_ui::test_tc_ui_003_coupon_discount_is_reflected_in_the_total` |
