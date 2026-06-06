import json
from pathlib import Path
from typing import Dict, Optional

_CONFIG_CACHE = {}
_FLOW_CACHE = {}

def get_interactive_config(industry: str, action: str) -> Optional[Dict]:
    """Return interactive definition for a given industry and action."""
    if industry not in _CONFIG_CACHE:
        config_path = Path(__file__).parent / "configs" / f"{industry}.json"
        if not config_path.exists():
            _CONFIG_CACHE[industry] = {}
        else:
            with open(config_path, "r") as f:
                _CONFIG_CACHE[industry] = json.load(f)
    return _CONFIG_CACHE.get(industry, {}).get(action)


def get_default_conversation_flow(industry: str, flow_type: str = "buyer") -> Optional[list]:
    """Return a default conversation flow step list for the given industry."""
    cache_key = f"{industry}:{flow_type}"
    if cache_key not in _FLOW_CACHE:
        flow_path = Path(__file__).parent / "configs" / f"{industry}_flow.json"
        if not flow_path.exists():
            _FLOW_CACHE[cache_key] = None
        else:
            with open(flow_path, "r") as f:
                flow_data = json.load(f)
            if isinstance(flow_data, dict) and flow_data.get("flow_type") == flow_type:
                _FLOW_CACHE[cache_key] = flow_data.get("steps")
            elif isinstance(flow_data, list):
                _FLOW_CACHE[cache_key] = flow_data
            else:
                _FLOW_CACHE[cache_key] = flow_data.get("steps") if isinstance(flow_data, dict) else None
    return _FLOW_CACHE.get(cache_key)
