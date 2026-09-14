from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Item:
    sku: str
    price: Decimal
    quantity: int


@dataclass
class Customer:
    email: str


@dataclass
class Order:
    customer: Customer
    items: list[Item]
    total: Decimal
    id: int | None = field(default=None)


@dataclass
class OrderRequest:
    email: str
    items: list[Item]
    coupon: str | None = None


@dataclass
class OrderResponse:
    order_id: int | None
    total: Decimal
