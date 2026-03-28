"""
Locust traffic generator for AcmeCorp e-commerce platform.

Simulates realistic user behavior patterns:
  - 40% Browse (view products)
  - 35% Abandon cart (add items but don't checkout)
  - 20% Full checkout (browse → add → pay)
  - 5%  Check order status

Usage:
  locust -f locustfile.py --host=http://localhost:3000 --users=50 --spawn-rate=5
"""

import random
import json
from locust import HttpUser, task, between, tag


PRODUCT_IDS = list(range(1, 21))  # 20 seeded products


class BrowsingUser(HttpUser):
    """Represents a typical storefront visitor."""

    wait_time = between(1, 5)
    weight = 40  # 40% of users

    @tag("browse")
    @task(5)
    def view_product_list(self):
        self.client.get("/api/products", name="/api/products")

    @tag("browse")
    @task(3)
    def view_product_detail(self):
        pid = random.choice(PRODUCT_IDS)
        self.client.get(f"/api/products/{pid}", name="/api/products/:id")

    @tag("health")
    @task(1)
    def check_health(self):
        self.client.get("/api/health-aggregate", name="/api/health-aggregate")


class CartAbandonUser(HttpUser):
    """Adds items to cart but never completes checkout."""

    wait_time = between(2, 6)
    weight = 35  # 35% of users

    @tag("browse")
    @task(3)
    def browse_products(self):
        self.client.get("/api/products", name="/api/products")

    @tag("cart")
    @task(5)
    def add_to_cart(self):
        pid = random.choice(PRODUCT_IDS)
        # View product first (realistic)
        self.client.get(f"/api/products/{pid}", name="/api/products/:id")
        # Reserve inventory
        self.client.post(
            f"/api/products/{pid}/reserve",
            json={"quantity": random.randint(1, 3)},
            name="/api/products/:id/reserve",
        )


class CheckoutUser(HttpUser):
    """Full shopping flow: browse → add → checkout → check status."""

    wait_time = between(3, 8)
    weight = 20  # 20% of users

    @tag("browse")
    @task(2)
    def browse(self):
        self.client.get("/api/products", name="/api/products")

    @tag("checkout")
    @task(3)
    def full_checkout(self):
        # Pick 1-3 random products
        num_items = random.randint(1, 3)
        items = []
        for _ in range(num_items):
            pid = random.choice(PRODUCT_IDS)
            qty = random.randint(1, 2)

            # View product
            resp = self.client.get(
                f"/api/products/{pid}", name="/api/products/:id"
            )
            if resp.status_code == 200:
                product = resp.json()
                items.append(
                    {
                        "product_id": pid,
                        "quantity": qty,
                        "price": product.get("price", "9.99"),
                    }
                )
                # Reserve
                self.client.post(
                    f"/api/products/{pid}/reserve",
                    json={"quantity": qty},
                    name="/api/products/:id/reserve",
                )

        if items:
            # Create order
            order_data = {
                "customer_email": f"user{random.randint(1, 1000)}@example.com",
                "items": items,
            }
            resp = self.client.post(
                "/api/orders",
                json=order_data,
                name="/api/orders",
            )
            if resp.status_code in (200, 201):
                order = resp.json()
                order_id = order.get("id")
                if order_id:
                    # Check order status after a delay
                    self.client.get(
                        f"/api/orders/{order_id}",
                        name="/api/orders/:id",
                    )


class OrderStatusUser(HttpUser):
    """Repeatedly checks order status (simulates anxious customer)."""

    wait_time = between(5, 15)
    weight = 5  # 5% of users

    @tag("status")
    @task
    def check_random_order(self):
        order_id = random.randint(1, 100)
        self.client.get(
            f"/api/orders/{order_id}", name="/api/orders/:id"
        )
