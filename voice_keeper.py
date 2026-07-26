import asyncio
import discord
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    import pytz as ZoneInfo # Fallback, though 3.12 has zoneinfo

from logger import logger

# Global state to prevent spamming the same log messages every check_interval
_last_status = None

def is_active_time(start_time: str, end_time: str, tz_name: str) -> bool:
    """
    Checks if the current time is within the active schedule.
    """
    try:
        tz = ZoneInfo(tz_name)
        now = datetime.now(tz).time()
    except Exception as e:
        logger.error(f"Timezone error ({tz_name}): {e}. Defaulting to active.")
        return True # Fallback to active if timezone is invalid
        
    start = datetime.strptime(start_time, "%H:%M").time()
    end = datetime.strptime(end_time, "%H:%M").time()
    
    if start <= end:
        return start <= now <= end
    else:
        # Schedule spans across midnight (e.g., 22:00 to 06:00)
        return start <= now or now <= end

async def connect_if_needed(client: discord.Client, guild_id: int, channel_id: int) -> None:
    """
    Connects to the specified voice channel if not already connected.
    Also handles moving to the correct channel if connected to the wrong one.
    """
    global _last_status
    
    guild = client.get_guild(guild_id)
    if not guild:
        if _last_status != "guild_not_found":
            logger.error(f"Guild with ID {guild_id} not found.")
            _last_status = "guild_not_found"
        return

    channel = guild.get_channel(channel_id)
    if not channel or not isinstance(channel, discord.VoiceChannel):
        if _last_status != "channel_not_found":
            logger.error(f"Voice channel with ID {channel_id} not found in guild {guild.name}.")
            _last_status = "channel_not_found"
        return

    voice_client: discord.VoiceClient = discord.utils.get(client.voice_clients, guild=guild)

    if voice_client:
        if voice_client.is_connected():
            if voice_client.channel.id == channel_id:
                if _last_status != "in_target":
                    logger.info("Already in target channel")
                    _last_status = "in_target"
            else:
                logger.warning(f"Connected to wrong channel ({voice_client.channel.name}). Moving to target...")
                try:
                    await voice_client.move_to(channel, self_mute=True, self_deaf=True)
                    logger.info(f"Joined voice channel (Muted & Deafened)")
                    _last_status = "in_target"
                except Exception as e:
                    logger.error(f"Failed to move to target channel: {e}")
                    _last_status = "move_failed"
        else:
            if _last_status != "reconnecting_auto":
                logger.info("Voice connection dropped, waiting for discord.py to auto-reconnect...")
                _last_status = "reconnecting_auto"
    else:
        if _last_status == "in_target":
            logger.warning("Disconnected from voice")
            
        logger.info(f"Connecting to voice channel...")
        try:
            await channel.connect(self_mute=True, self_deaf=True)
            logger.info("Joined voice channel (Muted & Deafened)")
            _last_status = "in_target"
        except Exception as e:
            if _last_status != "connect_failed":
                logger.error(f"Failed to connect to voice channel: {e}")
                _last_status = "connect_failed"

async def disconnect_if_connected(client: discord.Client, guild_id: int) -> None:
    """
    Disconnects from voice if currently connected (used when outside active hours).
    """
    global _last_status
    guild = client.get_guild(guild_id)
    if not guild:
        return
        
    voice_client: discord.VoiceClient = discord.utils.get(client.voice_clients, guild=guild)
    if voice_client and voice_client.is_connected():
        logger.info("Outside active hours. Disconnecting from voice...")
        try:
            await voice_client.disconnect(force=True)
            _last_status = "disconnected_scheduled"
        except Exception as e:
            logger.error(f"Failed to disconnect: {e}")
    elif _last_status != "disconnected_scheduled":
        logger.info("Outside active hours. Sleeping until active time...")
        _last_status = "disconnected_scheduled"

async def ensure_voice_connection(client: discord.Client, guild_id: int, channel_id: int) -> None:
    """
    Checks connection status and attempts to connect or move if needed.
    """
    await connect_if_needed(client, guild_id, channel_id)

async def monitor_loop(client: discord.Client, config: dict) -> None:
    """
    Background loop that continuously checks and maintains the voice connection.
    Runs every `check_interval` seconds.
    """
    await client.wait_until_ready()
    logger.info("Starting voice connection monitor loop...")
    
    guild_id = config.get("guild_id")
    channel_id = config.get("voice_channel_id")
    check_interval = config.get("check_interval", 5)
    schedule = config.get("schedule", {})

    while not client.is_closed():
        try:
            # Dynamically reload config to apply Web Panel changes instantly
            from utils import load_config
            current_config = load_config()
            guild_id = current_config.get("guild_id")
            channel_id = current_config.get("voice_channel_id")
            schedule = current_config.get("schedule", {})
            check_interval = current_config.get("check_interval", 5)

            if schedule.get("enabled"):
                is_active = is_active_time(
                    schedule.get("start_time"), 
                    schedule.get("end_time"), 
                    schedule.get("timezone", "UTC")
                )
                if is_active:
                    await ensure_voice_connection(client, guild_id, channel_id)
                else:
                    await disconnect_if_connected(client, guild_id)
            else:
                # Schedule is disabled -> disconnect if connected
                await disconnect_if_connected(client, guild_id)
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")
        
        await asyncio.sleep(check_interval)

async def reconnect(client: discord.Client, config: dict) -> None:
    """
    Forces a reconnection by disconnecting first, then relying on the monitor loop.
    """
    logger.info("Forcing reconnect process...")
    guild_id = config.get("guild_id")
    guild = client.get_guild(guild_id)
    if guild:
        voice_client: discord.VoiceClient = discord.utils.get(client.voice_clients, guild=guild)
        if voice_client and voice_client.is_connected():
            logger.warning("Disconnected from voice (Forced reconnect)")
            try:
                await voice_client.disconnect(force=True)
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")
