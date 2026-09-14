from decimal import Decimal


def clean_email(email: str) -> str:
    return email.strip().lower()


def calculate_total(items, coupon) -> Decimal:
    subtotal = sum(item.price * item.quantity for item in items)
    if coupon == "SAVE10":
        discount = subtotal * Decimal("0.10")
    else:
        discount = Decimal("0")
    tax = (subtotal - discount) * Decimal("0.08")
    return subtotal - discount + tax
