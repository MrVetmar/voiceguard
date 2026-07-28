"""
Ses kanali baglantisini kuran ve koruyan arka plan dongusu.

Aktiflik iki bagimsiz anahtarla belirlenir:
  * config["enabled"]           -> master switch (panelden Baslat/Durdur)
  * config["schedule"]["enabled"] -> saat kisiti; kapaliysa 7/24 aktif
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

import discord

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    from pytz import timezone as ZoneInfo

from config_store import store
from logger import logger
import runtime_state


def is_active_time(start_time: str, end_time: str, tz_name: str) -> bool:
    """Simdiki saatin zamanlama araliginda olup olmadigini soyler."""
    try:
        now = datetime.now(ZoneInfo(tz_name)).time()
        start = datetime.strptime(start_time, "%H:%M").time()
        end = datetime.strptime(end_time, "%H:%M").time()
    except Exception as exc:
        logger.error(f"Zamanlama okunamadi ({tz_name} / {start_time}-{end_time}): {exc}. Aktif kabul ediliyor.")
        return True

    if start <= end:
        return start <= now <= end
    # Gece yarisini asan aralik (orn. 22:00 -> 06:00)
    return start <= now or now <= end


def should_be_connected(config: Dict[str, Any]) -> bool:
    """Master switch ve zamanlamayi birlestirerek hedef durumu hesaplar."""
    if not config.get("enabled", True):
        return False

    schedule = config.get("schedule") or {}
    if not schedule.get("enabled"):
        return True  # Zamanlama kapali -> 7/24 aktif

    return is_active_time(
        schedule.get("start_time", "00:00"),
        schedule.get("end_time", "23:59"),
        schedule.get("timezone", "UTC"),
    )


def _voice_client(client: discord.Client, guild: discord.Guild) -> Optional[discord.VoiceClient]:
    return discord.utils.get(client.voice_clients, guild=guild)


def _log_once(guild_id: int, status: str, message: str, level: str = "info") -> None:
    """Ayni durum tekrar ederken log'u spam'lememek icin durum degisiminde loglar."""
    if runtime_state.get_status(guild_id) == status:
        return
    getattr(logger, level)(message)


async def connect_if_needed(client: discord.Client, guild_id: int, channel_id: int) -> None:
    """Hedef ses kanalinda degilse baglanir; yanlis kanaldaysa tasinir."""
    guild = client.get_guild(guild_id)
    if not guild:
        _log_once(guild_id, "guild_not_found", f"Sunucu bulunamadi (ID: {guild_id})", "error")
        runtime_state.set_voice(guild_id, connected=False, status="guild_not_found")
        return

    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.VoiceChannel):
        _log_once(
            guild_id,
            "channel_not_found",
            f"Ses kanali bulunamadi (ID: {channel_id}, sunucu: {guild.name})",
            "error",
        )
        runtime_state.set_voice(
            guild_id, connected=False, status="channel_not_found", guild_name=guild.name
        )
        return

    voice_client = _voice_client(client, guild)

    if voice_client and voice_client.is_connected():
        if voice_client.channel.id == channel_id:
            _log_once(guild_id, "connected", "Hedef kanalda")
            runtime_state.set_voice(
                guild_id,
                connected=True,
                status="connected",
                channel_id=channel.id,
                channel_name=channel.name,
                guild_name=guild.name,
            )
            return

        logger.warning(f"Yanlis kanaldayiz ({voice_client.channel.name}). Hedefe tasiniyor...")
        try:
            await voice_client.move_to(channel, self_mute=True, self_deaf=True)
            logger.info(f"'{channel.name}' kanalina gecildi (Muted & Deafened)")
            runtime_state.set_voice(
                guild_id,
                connected=True,
                status="connected",
                channel_id=channel.id,
                channel_name=channel.name,
                guild_name=guild.name,
            )
        except Exception as exc:
            logger.error(f"Hedef kanala tasinamadi: {exc}")
            runtime_state.record_error(f"move_to: {exc}")
            runtime_state.set_voice(
                guild_id, connected=False, status="move_failed", guild_name=guild.name
            )
        return

    if voice_client:
        # Nesne var ama bagli degil: discord.py kendi otomatik yeniden baglanmasini yapiyor.
        _log_once(guild_id, "reconnecting", "Ses baglantisi dustu, otomatik yeniden baglanma bekleniyor...")
        runtime_state.set_voice(
            guild_id, connected=False, status="reconnecting", guild_name=guild.name
        )
        return

    _log_once(guild_id, "connecting", f"'{channel.name}' kanalina baglaniliyor...")
    runtime_state.set_voice(guild_id, connected=False, status="connecting", guild_name=guild.name)
    try:
        await channel.connect(self_mute=True, self_deaf=True)
        logger.info(f"'{channel.name}' kanalina baglanildi (Muted & Deafened)")
        runtime_state.set_voice(
            guild_id,
            connected=True,
            status="connected",
            channel_id=channel.id,
            channel_name=channel.name,
            guild_name=guild.name,
        )
    except Exception as exc:
        _log_once(guild_id, "connect_failed", f"Ses kanalina baglanilamadi: {exc}", "error")
        runtime_state.record_error(f"connect: {exc}")
        runtime_state.set_voice(
            guild_id, connected=False, status="connect_failed", guild_name=guild.name
        )


async def disconnect_if_connected(client: discord.Client, guild_id: int, reason: str) -> None:
    """Aktif olmamasi gereken durumlarda ses baglantisini kapatir."""
    guild = client.get_guild(guild_id)
    if not guild:
        return

    voice_client = _voice_client(client, guild)
    if voice_client and voice_client.is_connected():
        logger.info(f"{reason} Ses kanalindan cikiliyor...")
        try:
            await voice_client.disconnect(force=True)
        except Exception as exc:
            logger.error(f"Ses kanalindan cikilamadi: {exc}")
            runtime_state.record_error(f"disconnect: {exc}")
    else:
        _log_once(guild_id, reason_status(reason), f"{reason} Bekleniyor...")

    runtime_state.set_voice(
        guild_id, connected=False, status=reason_status(reason), guild_name=guild.name
    )


def reason_status(reason: str) -> str:
    return "stopped" if "durduruldu" in reason.lower() else "outside_schedule"


async def force_reconnect(client: discord.Client, config: Dict[str, Any]) -> None:
    """Mevcut baglantiyi keser; monitor dongusu bir sonraki turda yeniden baglanir."""
    guild_id = config.get("guild_id")
    guild = client.get_guild(guild_id) if guild_id else None
    if not guild:
        logger.warning("Yeniden baglanma istendi ama sunucu bulunamadi")
        return

    voice_client = _voice_client(client, guild)
    if voice_client:
        try:
            await voice_client.disconnect(force=True)
            logger.info("Baglanti kesildi, yeniden baglanilacak")
        except Exception as exc:
            logger.error(f"Yeniden baglanma sirasinda hata: {exc}")
            runtime_state.record_error(f"reconnect: {exc}")
    runtime_state.set_voice(guild_id, connected=False, status="reconnecting", guild_name=guild.name)


async def monitor_loop(client: discord.Client) -> None:
    """Ses baglantisini periyodik olarak kontrol eden arka plan gorevi."""
    await client.wait_until_ready()
    logger.info("Ses baglanti izleyicisi basladi")

    while not client.is_closed():
        interval = 5
        try:
            config = store.get()
            interval = config.get("check_interval", 5)
            guild_id = config.get("guild_id")
            channel_id = config.get("voice_channel_id")

            if not guild_id or not channel_id:
                _log_once(
                    guild_id or 0,
                    "unconfigured",
                    "Sunucu/kanal ID'si ayarlanmamis. Panelden yapilandirin.",
                    "warning",
                )
                runtime_state.set_voice(guild_id or 0, connected=False, status="unconfigured")
            elif not config.get("enabled", True):
                await disconnect_if_connected(client, guild_id, "Bot panelden durduruldu.")
            elif should_be_connected(config):
                await connect_if_needed(client, guild_id, channel_id)
            else:
                await disconnect_if_connected(client, guild_id, "Zamanlama disinda.")
        except Exception as exc:
            logger.error(f"Izleyici dongusunde hata: {type(exc).__name__}: {exc}")
            runtime_state.record_error(f"monitor_loop: {exc}")

        await asyncio.sleep(interval)
