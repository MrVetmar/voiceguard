"""
Botun canli calisma durumu. Panelin /api/status endpoint'i buradan beslenir.

Modul seviyesinde tek bir sozluk yerine guild bazli kayit tutulur, boylece
ileride birden fazla sunucu desteklenebilir.
"""

import time
from typing import Any, Dict, Optional

_started_at = time.time()

_discord: Dict[str, Any] = {
    "ready": False,
    "user": None,
    "user_id": None,
    "resumed_count": 0,
    "last_disconnect": None,
}

# {guild_id: {...}}
_guilds: Dict[int, Dict[str, Any]] = {}

_last_error: Optional[Dict[str, Any]] = None
_last_action: Optional[Dict[str, Any]] = None


def _guild(guild_id: int) -> Dict[str, Any]:
    if guild_id not in _guilds:
        _guilds[guild_id] = {
            "guild_id": guild_id,
            "guild_name": None,
            "connected": False,
            "channel_id": None,
            "channel_name": None,
            "status": "idle",
            "since": time.time(),
        }
    return _guilds[guild_id]


def mark_ready(user: str, user_id: int) -> None:
    _discord["ready"] = True
    _discord["user"] = user
    _discord["user_id"] = user_id


def mark_resumed() -> None:
    _discord["resumed_count"] += 1


def mark_disconnected() -> None:
    _discord["last_disconnect"] = time.time()


def set_voice(
    guild_id: int,
    *,
    connected: bool,
    status: str,
    channel_id: Optional[int] = None,
    channel_name: Optional[str] = None,
    guild_name: Optional[str] = None,
) -> None:
    """Bir sunucudaki ses baglanti durumunu gunceller."""
    entry = _guild(guild_id)
    changed = entry["connected"] != connected or entry["status"] != status
    entry["connected"] = connected
    entry["status"] = status
    entry["channel_id"] = channel_id
    entry["channel_name"] = channel_name
    if guild_name:
        entry["guild_name"] = guild_name
    if changed:
        entry["since"] = time.time()


def get_status(guild_id: int) -> str:
    """Bir sunucunun son bilinen durum etiketini dondurur."""
    return _guild(guild_id)["status"]


def record_error(message: str) -> None:
    global _last_error
    _last_error = {"message": message, "at": time.time()}


def record_action(action: str, source: str = "panel") -> None:
    global _last_action
    _last_action = {"action": action, "source": source, "at": time.time()}


def _serialize(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Snowflake ID'leri string'e cevirir.

    Discord ID'leri 2^53'u astigi icin JSON sayisi olarak gonderilirse
    JavaScript tarafinda hassasiyet kaybeder.
    """
    out = dict(entry)
    for key in ("guild_id", "channel_id"):
        out[key] = str(out[key]) if out.get(key) else None
    return out


def snapshot(active_conversations: int = 0) -> Dict[str, Any]:
    """Panele gonderilecek tam durum ozeti."""
    discord_info = dict(_discord)
    discord_info["user_id"] = str(discord_info["user_id"]) if discord_info["user_id"] else None

    return {
        "uptime_seconds": int(time.time() - _started_at),
        "started_at": _started_at,
        "discord": discord_info,
        "guilds": [_serialize(entry) for entry in _guilds.values()],
        "active_conversations": active_conversations,
        "last_error": dict(_last_error) if _last_error else None,
        "last_action": dict(_last_action) if _last_action else None,
        "server_time": time.time(),
    }
