"""Cost ledger tests: hand-computed example + both call shapes.

Hand computation for the fixture below (2 acres wheat):
  DAP:   1.5 bags/acre x 2 acres x 12000 = 36000
  Urea:  2.0 bags/acre x 2 acres x  4500 = 18000
  seed 8000 + labor 15000                    = 23000
  total = 77000 ; per acre = 38500
  revenue = 40 maunds/acre x 2 x 4000 = 320000
  profit  = 320000 - 77000 = 243000
  breakeven = 77000 / (2 x 4000) = 9.625 maunds/acre -> rounded to 9.62
"""
import pytest

from app.services.costs import calculate

BAGS = {"DAP": 1.5, "Urea": 2.0}
PRICES = {"DAP": 12000.0, "Urea": 4500.0}
OTHER = {"seed": 8000.0, "labor": 15000.0}


def test_hand_computed_ledger():
    out = calculate("wheat", 2.0, fertilizer_bags=BAGS,
                    fertilizer_prices=PRICES, other=OTHER,
                    expected_yield_maunds_per_acre=40.0,
                    expected_price_per_maund=4000.0)
    assert out["total_cost"] == 77000.0
    assert out["per_acre_cost"] == 38500.0
    assert out["revenue"] == 320000.0
    assert out["profit"] == 243000.0
    assert out["breakeven_yield"] == pytest.approx(9.62)
    assert out["breakeven_yield_maunds_per_acre"] == pytest.approx(9.62)
    labels = [li["label"] for li in out["line_items"]]
    assert any("DAP" in label for label in labels)
    assert any("Seed" in label for label in labels)
    dap = next(li for li in out["line_items"] if "DAP" in li["label"])
    assert dap["qty"] == 1.5 and dap["unit"] == "bags/acre"
    assert dap["rate"] == 12000.0 and dap["amount"] == 36000.0


def test_route_call_shape_items():
    """The shape the Flask route actually passes: items list + kwargs."""
    items = [
        {"name": "DAP", "bags": 1.5, "price_per_bag": 12000.0},
        {"name": "Urea", "bags": 2.0, "price_per_bag": 4500.0},
    ]
    out = calculate(crop="wheat", acres=2.0, items=items,
                    expected_yield_maunds=40.0, expected_price=4000.0)
    assert out["total_cost"] == 54000.0  # no `other` in route shape
    assert out["revenue"] == 320000.0
    assert out["profit"] == 266000.0


def test_zero_price_gives_none_breakeven():
    """Breakeven with price 0 is undefined -> None, never ZeroDivision."""
    out = calculate("wheat", 1.0, fertilizer_bags={"DAP": 1.0},
                    fertilizer_prices={"DAP": 12000.0},
                    expected_yield_maunds_per_acre=40.0,
                    expected_price_per_maund=0.0)
    assert out["breakeven_yield"] is None
    assert out["profit"] == -12000.0


def test_validation():
    with pytest.raises(ValueError, match="greater than 0"):
        calculate("wheat", 0, fertilizer_bags=BAGS, fertilizer_prices=PRICES)
    with pytest.raises(ValueError, match="cannot be negative"):
        calculate("wheat", 1.0, fertilizer_bags={"DAP": -1},
                  fertilizer_prices=PRICES)
    with pytest.raises(ValueError, match="No price given"):
        calculate("wheat", 1.0, fertilizer_bags={"DAP": 1},
                  fertilizer_prices={})
    with pytest.raises(ValueError, match="must be a number"):
        calculate("wheat", "two", fertilizer_bags=BAGS,
                  fertilizer_prices=PRICES)
