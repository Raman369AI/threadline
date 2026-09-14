from .models import Order


class OrderRepository:
    def __init__(self, connection):
        self.connection = connection

    def save(self, order: Order) -> Order:
        cursor = self.connection.execute(
            "INSERT INTO orders (email, total) VALUES (?, ?)",
            (order.customer.email, str(order.total)),
        )
        self.connection.commit()
        order.id = cursor.lastrowid
        return order
