from abc import ABC, abstractmethod

class BaseIntentClassifier(ABC):
    @abstractmethod
    def classify(self, text: str) -> str:
        pass
    @abstractmethod
    def extract_entities(self, text: str) -> dict:
        pass

class BaseState(ABC):
    def __init__(self):
        self.required_fields = []
        self.confirmed = False

    @abstractmethod
    def is_complete(self) -> bool:
        return all(getattr(self, field, None) for field in self.required_fields)

    def reset(self):
        self.__init__()

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def from_dict(self, data: dict):
        for k, v in data.items():
            setattr(self, k, v)

class BaseRulesEngine(ABC):
    def __init__(self):
        self.required_fields = []

    def process_confirmation(self, user_text: str, state: BaseState):
        if state.is_complete() and not state.confirmed:
            if any(word in user_text.lower() for word in ["yes", "haan", "confirm", "theek", "ok", "book", "done"]):
                state.confirmed = True
                return {"action": "confirm_booking", "data": {"state": state.to_dict()}}
            else:
                return {"action": "ask_confirmation", "data": {"state": state.to_dict()}}
        return None

    @abstractmethod
    def process(self, user_text: str, state: BaseState) -> dict:
        pass

class BasePrompts(ABC):
    @abstractmethod
    def get_system_prompt(self) -> str:
        pass

    @abstractmethod
    def get_action_prompt(self, action: str, data: dict) -> str:
        pass

    @abstractmethod
    def get_rule_reply(self, action: str, data: dict) -> str | None:
        """Return a static reply for rule mode, or None if the action requires LLM."""
        pass