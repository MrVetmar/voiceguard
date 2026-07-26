import json
import os
from typing import Any, Dict

def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """
    Loads configuration from a JSON file.
    If config.json doesn't exist, falls back to environment variables (for Railway/cloud deployment).
    
    Args:
        config_path (str): The path to the configuration file.
        
    Returns:
        Dict[str, Any]: Parsed configuration dictionary.
    """
    # If config.json exists, use it (local development)
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        # Fall back to environment variables (Railway / cloud deployment)
        config = {
            "token": os.environ.get("DISCORD_TOKEN", ""),
            "guild_id": int(os.environ.get("GUILD_ID", "0")),
            "voice_channel_id": int(os.environ.get("VOICE_CHANNEL_ID", "0")),
            "check_interval": int(os.environ.get("CHECK_INTERVAL", "5")),
            "schedule": {
                "enabled": os.environ.get("SCHEDULE_ENABLED", "true").lower() == "true",
                "start_time": os.environ.get("SCHEDULE_START", "09:00"),
                "end_time": os.environ.get("SCHEDULE_END", "23:00"),
                "timezone": os.environ.get("TIMEZONE", "Europe/Istanbul"),
            },
            "greeting_channel_id": int(os.environ.get("GREETING_CHANNEL_ID", "0")),
            "nvidia_api_key": os.environ.get("NVIDIA_API_KEY", ""),
        }
        
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
