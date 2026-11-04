"""Fertilizer / input cost calculator — pure ledger math.

Two call shapes are supported (WHY: the spec and the already-written route
disagree, and the service must satisfy both without a rewrite on either
side):
  spec shape:  calculate(crop, acres, fertilizer_bags={name: bags_per_acre},
                         fertilizer_prices={name: price_pkr},
                         other={seed:.., pesticide:.., labor:.., diesel:.., water:..},
                         expected_yield_maunds_per_acre=.., expected_price_per_maund=..)
  route shape: calculate(crop, acres, items=[{name, bags, price_per_bag}, ...],
                         expected_yield_maunds=.., expected_price=..)
               — items' `bags` is interpreted as BAGS PER ACRE, consistent
               with the spec's formula (bags_per_acre x acres x price).

Core formula: fertilizer cost = bags_per_acre x acres x price_per_bag.
Revenue = yield_maunds_per_acre x acres x price_per_maund.
Breakeven yield = total_cost / (acres x price_per_maund): the yield at
which the farmer exactly recovers costs — the single most useful number
for a viva ("how many maunds must I harvest to not lose money?").
"""

OTHER_LABELS = {
    "seed": "Seed",
    "pesticide": "Pesticide / spray",
    "labor": "Labor",
    "diesel": "Diesel / fuel",
    "water": "Water / irrigation",
}


def _num(value, name):
    """Coerce to float, rejecting NaN/inf and non-numerics with a clear error."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {value!r}.") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be a finite number.")
    return number


def calculate(crop, acres, fertilizer_bags=None, fertilizer_prices=None,
              other=None, expected_yield_maunds_per_acre=None,
              expected_price_per_maund=None, *, items=None,
              expected_yield_maunds=None, expected_price=None):
    """Build the full cost ledger for one crop on one field.

    Returns dict with:
      line_items: [{label, name, qty, unit, rate, amount}] — printable rows
      total_cost (+ alias total), per_acre_cost (+ alias per_acre),
      revenue, profit, breakeven_yield (+ alias breakeven_yield_maunds_per_acre)
      crop, acres.
    breakeven_yield is None when the expected price is 0 — WHY None and not
    0 or crash: dividing by zero price is meaningless, and the template can
    show "—" for it.
    """
    # ---- normalize the two call shapes into one internal form ----
    if items is not None:
        fertilizer_bags = {}
        fertilizer_prices = {}
        for it in items:
            name = str(it.get("name", "")).strip()
            if not name:
                raise ValueError("Each fertilizer item needs a name.")
            fertilizer_bags[name] = it.get("bags", 0)
            fertilizer_prices[name] = it.get("price_per_bag", 0)
        if expected_yield_maunds_per_acre is None:
            expected_yield_maunds_per_acre = expected_yield_maunds
        if expected_price_per_maund is None:
            expected_price_per_maund = expected_price

    fertilizer_bags = fertilizer_bags or {}
    fertilizer_prices = fertilizer_prices or {}
    other = other or {}

    if not crop or not str(crop).strip():
        raise ValueError("crop is required.")
    acres = _num(acres, "acres")
    if acres <= 0:
        raise ValueError("acres must be greater than 0.")
    yld = _num(expected_yield_maunds_per_acre or 0,
               "expected_yield_maunds_per_acre")
    price = _num(expected_price_per_maund or 0, "expected_price_per_maund")
    if yld < 0:
        raise ValueError("expected yield cannot be negative.")
    if price < 0:
        raise ValueError("expected price cannot be negative.")

    line_items = []
    total = 0.0

    # ---- fertilizer lines ----
    for name in fertilizer_bags:
        bags_per_acre = _num(fertilizer_bags[name], f"bags for {name}")
        if bags_per_acre < 0:
            raise ValueError(f"bags for {name} cannot be negative.")
        if name not in fertilizer_prices:
            raise ValueError(f"No price given for fertilizer '{name}'.")
        bag_price = _num(fertilizer_prices[name], f"price for {name}")
        if bag_price <= 0:
            raise ValueError(f"price for {name} must be positive.")
        amount = bags_per_acre * acres * bag_price
        total += amount
        line_items.append({
            "label": f"{name} fertilizer",
            "name": name,
            "qty": bags_per_acre,
            "unit": "bags/acre",
            "rate": bag_price,
            "amount": round(amount, 2),
        })

    # ---- other input costs (lump sums for the whole field) ----
    for key, value in other.items():
        cost = _num(value, f"other cost '{key}'")
        if cost < 0:
            raise ValueError(f"other cost '{key}' cannot be negative.")
        if cost == 0:
            continue  # WHY skip zeros: keeps the printed ledger clean
        total += cost
        line_items.append({
            "label": OTHER_LABELS.get(str(key).lower(), str(key).title()),
            "name": str(key),
            "qty": 1,
            "unit": "lump sum",
            "rate": round(cost, 2),
            "amount": round(cost, 2),
        })

    total = round(total, 2)
    per_acre = round(total / acres, 2)
    revenue = round(yld * acres * price, 2)
    profit = round(revenue - total, 2)
    breakeven = round(total / (acres * price), 2) if price > 0 else None

    return {
        "crop": str(crop).strip(),
        "acres": acres,
        "line_items": line_items,
        "total_cost": total,
        "total": total,  # alias used by older callers
        "per_acre_cost": per_acre,
        "per_acre": per_acre,  # alias
        "revenue": revenue,
        "profit": profit,
        "breakeven_yield": breakeven,
        "breakeven_yield_maunds_per_acre": breakeven,  # alias
    }
