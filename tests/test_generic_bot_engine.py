import pytest
from modules.ai.generic_bot_engine import GenericBotEngine

SAMPLE_CONFIG = {
    "fields": [
        {"name": "name", "question": "What is your name?", "type": "text", "required": True},
        {"name": "age", "question": "What is your age?", "type": "text", "required": True}
    ],
    "confirmation": {"enabled": True, "message": "Confirm your details:"}
}

def test_normal_flow():
    engine = GenericBotEngine(SAMPLE_CONFIG)
    state = {"responses": {}}
    
    # First ask name
    action = engine.process("Hello", state)
    assert action["action"] == "ask"
    assert "name" in action["data"]["question"]
    
    # Provide name
    state["responses"]["name"] = "Alice"
    action = engine.process("Alice", state)
    assert action["action"] == "ask"
    assert "age" in action["data"]["question"]
    
    # Provide age
    state["responses"]["age"] = "30"
    action = engine.process("30", state)
    assert action["action"] == "ask_confirmation"
    
    # Confirm
    action = engine.process("Confirm", state)
    assert action["action"] == "create_lead"