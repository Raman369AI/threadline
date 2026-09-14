import logging

from .helpers import calculate_total, clean_email
from .models import Customer, Order

logger = logging.getLogger(__name__)


def place_order(email, items, coupon, repository, notifier):
    normalized_email = clean_email(email)
    if not items:
        raise ValueError("An order needs at least one item")

    total = calculate_total(items, coupon)
    customer = Customer(email=normalized_email)
    order = Order(customer=customer, items=items, total=total)
    saved = repository.save(order)
    logger.info("Order saved", extra={"order_id": saved.id})
    notifier.queue_receipt(saved.id, customer.email)
    return saved
