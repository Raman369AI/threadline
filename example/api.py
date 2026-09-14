from .models import OrderRequest, OrderResponse
from .repository import OrderRepository
from .service import place_order


def submit_order(request: OrderRequest, repository: OrderRepository, notifier) -> OrderResponse:
    order = place_order(
        request.email,
        request.items,
        request.coupon,
        repository,
        notifier,
    )
    return OrderResponse(order_id=order.id, total=order.total)
