from ..base import BaseState

class DefaultState(BaseState):
    def __init__(self):
        super().__init__()
        self.name = None
        self.phone = None
        self.query = None
        self.required_fields = []   # no mandatory fields for default

    def is_complete(self):
        return True   # default state is always “complete”