"""Read-only stock decisions, separated from HTTP and telemetry for testing."""

KEY_FIELDS = ("sku", "warehouse", "variant")
DEFAULT_BASKET = [
    {"line_id": f"line-{number}", "sku": "BOOK-001", "warehouse": "east", "variant": "paperback", "quantity": 1}
    for number in range(1, 7)
]
STOCK = {
    ("BOOK-001", "east", "paperback"): 20,
    ("BOOK-001", "west", "paperback"): 4,
    ("BOOK-001", "east", "hardback"): 2,
    ("BOOK-002", "east", "paperback"): 7,
}


class BasketValidationError(ValueError):
    pass


def stock_key(line):
    return tuple(line[field] for field in KEY_FIELDS)


def validate_basket(lines):
    if not isinstance(lines, list) or not 1 <= len(lines) <= 100:
        raise BasketValidationError("basket must contain 1 to 100 lines")
    ids = set()
    for line in lines:
        if not isinstance(line, dict):
            raise BasketValidationError("each basket line must be an object")
        for field in ("line_id", *KEY_FIELDS):
            value = line.get(field)
            if not isinstance(value, str) or not 1 <= len(value) <= 64:
                raise BasketValidationError(f"{field} must be a string of 1 to 64 characters")
        if line["line_id"] in ids:
            raise BasketValidationError("line_id must be unique within the basket")
        ids.add(line["line_id"])
        if type(line.get("quantity")) is not int or not 1 <= line["quantity"] <= 1000:
            raise BasketValidationError("quantity must be an integer from 1 to 1000")


def evaluate_basket(lines, per_line, fetch, reuse):
    """Fetch stock snapshots and compare them with total demand per stock key.

    fetch(line, scope) performs an HTTP lookup; reuse(line, scope) records a
    decision without another HTTP request. The cache lasts for this call only.
    This neither reserves stock nor promises availability when an order is placed.
    """
    validate_basket(lines)
    required = {}
    for line in lines:
        key = stock_key(line)
        required[key] = required.get(key, 0) + line["quantity"]
    snapshots = {}
    scope = "line" if per_line else "request"
    for line in lines:
        key = stock_key(line)
        if per_line or key not in snapshots:
            snapshots[key] = fetch(line, scope)
        else:
            reuse(line, scope)
    items = [{**dict(zip(KEY_FIELDS, key)), "required_quantity": quantity,
              "available_quantity": snapshots[key]}
             for key, quantity in sorted(required.items())]
    return {"outcome": "accepted" if all(item["available_quantity"] >= item["required_quantity"] for item in items)
            else "out_of_stock", "items": items}
