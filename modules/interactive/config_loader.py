import json
from pathlib import Path
from typing import Dict, Optional

_CONFIG_CACHE = {}

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