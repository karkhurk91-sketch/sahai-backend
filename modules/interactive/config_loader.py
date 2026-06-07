import json
import logging
from pathlib import Path
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)

_CONFIG_CACHE = {}
_FLOW_CACHE = {}

def get_interactive_config(industry: str, action: str) -> Optional[Dict]:
    """Return interactive definition for a given industry and action."""
    if industry not in _CONFIG_CACHE:
        config_path = Path(__file__).parent / "configs" / f"{industry}.json"
        if not config_path.exists():
            logger.warning(f"Interactive config file not found: {config_path}")
            _CONFIG_CACHE[industry] = {}
        else:
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    _CONFIG_CACHE[industry] = json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in {config_path}: {e}")
                _CONFIG_CACHE[industry] = {}
    return _CONFIG_CACHE.get(industry, {}).get(action)


def get_default_conversation_flow(industry: str, flow_type: str = "buyer") -> Optional[List[Dict]]:
    """
    Return a default conversation flow step list for the given industry.
    Returns None if no default flow is defined.
    """
    cache_key = f"{industry}:{flow_type}"
    if cache_key not in _FLOW_CACHE:
        flow_path = Path(__file__).parent / "configs" / f"{industry}_flow.json"
        if not flow_path.exists():
            logger.warning(f"Default flow file not found: {flow_path}")
            _FLOW_CACHE[cache_key] = None
        else:
            try:
                with open(flow_path, "r", encoding="utf-8") as f:
                    flow_data = json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in {flow_path}: {e}")
                _FLOW_CACHE[cache_key] = None
            else:
                # Determine the correct steps based on file structure
                if isinstance(flow_data, dict):
                    # If dict has 'flow_type' and 'steps', validate flow_type
                    if flow_data.get("flow_type") == flow_type:
                        steps = flow_data.get("steps", [])
                    else:
                        # Fallback to any steps key or treat whole dict as step? Better to return None
                        steps = flow_data.get("steps") if "steps" in flow_data else None
                elif isinstance(flow_data, list):
                    steps = flow_data
                else:
                    steps = None
                
                if steps is not None and not isinstance(steps, list):
                    logger.error(f"Invalid steps format in {flow_path}: expected list, got {type(steps)}")
                    steps = None
                
                _FLOW_CACHE[cache_key] = steps
    return _FLOW_CACHE.get(cache_key)