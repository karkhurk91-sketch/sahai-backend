from ..base import BaseState

class RestaurantState(BaseState):
    def __init__(self):
        super().__init__()
        self.order_items = {}          # {item_name: quantity}
        self.name = None
        self.phone = None
        self.delivery_preference = None
        self.confirmed = False
        self.ordering_flow = False     # flag to indicate ordering mode
        self.menu_prices = {
            "paneer butter masala": 250,
            "butter chicken": 320,
            "dal makhani": 180,
            "veg biryani": 200,
            "chicken biryani": 280,
            "garlic naan": 40,
            "butter naan": 35,
            "jeera rice": 120,
            "gulab jamun": 60,
            "ice cream": 80,
            "tandoori roti": 25,
            "mix veg": 160,
            "chicken tikka": 300,
        }
        self.required_fields = ["order_items", "name", "phone", "delivery_preference"]

    def is_complete(self):
        return self.order_items and self.name and self.phone and self.delivery_preference and self.confirmed

    def to_dict(self):
        return {
            "order_items": self.order_items,
            "name": self.name,
            "phone": self.phone,
            "delivery_preference": self.delivery_preference,
            "ordering_flow": self.ordering_flow,
            "confirmed": self.confirmed
        }

    def from_dict(self, data: dict):
        self.order_items = data.get("order_items", {})
        self.name = data.get("name")
        self.phone = data.get("phone")
        self.delivery_preference = data.get("delivery_preference")
        self.ordering_flow = data.get("ordering_flow", False)
        self.confirmed = data.get("confirmed", False)