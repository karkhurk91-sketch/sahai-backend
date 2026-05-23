from modules.ai.booking_helper import create_booking  # reuse existing

TOOLS = {
    "create_booking": {
        "function": create_booking,
        "description": "Create a booking appointment",
        "parameters": {"type": "object", "properties": {...}}
    },
    "check_availability": {
        "function": check_availability,
        "description": "Check slot availability"
    }
}

def execute_tool(tool_name: str, arguments: dict):
    if tool_name in TOOLS:
        return TOOLS[tool_name]["function"](**arguments)
    return None