from ..base import BaseState

class SalonState(BaseState):
    def __init__(self):
        super().__init__()
        self.service = None      # haircut, facial, etc.
        self.time = None         # e.g., "14:00"
        self.date = None         # "today", "tomorrow"
        self.name = None
        self.phone = None
        self.required_fields = ["service", "time", "name", "phone"]
        self.confirmed = False

    def to_dict(self):
        return {
            "service": self.service,
            "time": self.time,
            "date": self.date,
            "name": self.name,
            "phone": self.phone
        }