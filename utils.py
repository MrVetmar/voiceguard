import json
import os
from typing import Any, Dict

def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """
    Loads configuration from a JSON file.
    
    Args:
        config_path (str): The path to the configuration file.
        
    Returns:
        Dict[str, Any]: Parsed configuration dictionary.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file '{config_path}' not found.")
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    required_keys = ["token", "guild_id", "voice_channel_id", "check_interval"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required configuration key: '{key}'")
            
    schedule = config.get("schedule")
    if schedule and schedule.get("enabled"):
        sched_keys = ["start_time", "end_time", "timezone"]
        for sk in sched_keys:
            if sk not in schedule:
                raise ValueError(f"Missing required schedule key: '{sk}'")
            
    return config
