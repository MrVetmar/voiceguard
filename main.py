import discord
import asyncio
import re
import random
import time
from utils import load_config
from logger import logger
from voice_keeper import monitor_loop
from web_server import start_web_server
from chat_ai import ChatAI

class VoiceKeeperClient(discord.Client):
    """
    Custom Discord Client for managing the Voice Keeper functionality.
    """
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.monitor_task = None
        self.web_task = None
        self.greeted_users = {} # {user_id: last_greeted_timestamp}
        self.GREET_COOLDOWN = 900 # 15 minutes cooldown (in seconds)
        
        # Initialize AI chat module
        nvidia_key = config.get("nvidia_api_key", "")
        self.chat_ai = ChatAI(nvidia_key)

    async def setup_hook(self) -> None:
        """
        Called after login but before connecting to the gateway.
        This is the recommended place to start background tasks in discord.py 2.x.
        """
        self.monitor_task = self.loop.create_task(monitor_loop(self, self.config))
        self.web_task = self.loop.create_task(start_web_server())

    async def on_ready(self) -> None:
        """
        Event triggered when the client has successfully connected to Discord.
        """
        logger.info("Connected")
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        
    async def on_resumed(self) -> None:
        """
        Event triggered when the client resumes a session (Gateway reconnect).
        """
        logger.info("Session resumed (Gateway reconnect)")

    async def on_disconnect(self) -> None:
        """
        Event triggered when the client disconnects from the Discord Gateway.
        """
        logger.warning("Disconnected from Discord Gateway")

    async def on_message(self, message: discord.Message) -> None:
        """
        Listens for greeting messages and AI chat in the designated text channel.
        """
        # Ignore our own messages
        if message.author == self.user:
            return

        # Load config dynamically so panel updates apply immediately
        try:
            current_config = load_config()
        except Exception:
            current_config = self.config

        greeting_channel_id = current_config.get("greeting_channel_id")
        if not greeting_channel_id or message.channel.id != greeting_channel_id:
            return

        user_id = message.author.id
        username = message.author.display_name or message.author.name
        content = message.content.strip()

        # --- 1. Check for greeting ("sa", "selam" etc.) ---
        greeting_pattern = re.compile(
            r'\b(sa|sa\+|sa-|s\.a|selam|selamın aleyküm|selamun aleykum|selamun aleyküm|selamin aleykum)\b', 
            re.IGNORECASE
        )
        
        if greeting_pattern.search(content):
            # Cooldown check: ignore if this user was greeted recently
            last_greeted = self.greeted_users.get(user_id, 0)
            if time.time() - last_greeted < self.GREET_COOLDOWN:
                return
                
            logger.info(f"Greeting detected from {username} in channel {message.channel.id}")
            self.greeted_users[user_id] = time.time()
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
            async with message.channel.typing():
                await asyncio.sleep(random.uniform(0.8, 1.5))
            try:
                await message.reply("as hoş geldin", mention_author=False)
                logger.info("Greeting replied successfully")
            except Exception as e:
                logger.error(f"Failed to reply to greeting: {e}")
            return

        # --- 2. Check for "hb" (hoş bulduk) -> start AI chat ---
        hb_pattern = re.compile(r'\b(hb|hoş bulduk|hoşbulduk|hoş bulduk\.?)\b', re.IGNORECASE)
        
        if hb_pattern.search(content):
            logger.info(f"'hb' detected from {username}, starting AI conversation")
            # Start a fresh conversation
            self.chat_ai.start_conversation(user_id, username)
            
            ai_reply = await self.chat_ai.get_response(user_id, username, content)
            if ai_reply:
                await asyncio.sleep(random.uniform(0.5, 1.2))
                async with message.channel.typing():
                    # Typing duration based on reply length
                    type_duration = min(len(ai_reply) * 0.04, 2.0)
                    await asyncio.sleep(max(0.6, type_duration))
                try:
                    await message.reply(ai_reply, mention_author=False)
                    logger.info(f"AI replied to {username}: {ai_reply}")
                except Exception as e:
                    logger.error(f"Failed to send AI reply: {e}")
            return

        # --- 3. Continue existing AI conversation ---
        if self.chat_ai.has_active_conversation(user_id):
            logger.info(f"Continuing AI conversation with {username}")
            
            ai_reply = await self.chat_ai.get_response(user_id, username, content)
            if ai_reply:
                await asyncio.sleep(random.uniform(0.5, 1.2))
                async with message.channel.typing():
                    type_duration = min(len(ai_reply) * 0.04, 2.0)
                    await asyncio.sleep(max(0.6, type_duration))
                try:
                    await message.reply(ai_reply, mention_author=False)
                    logger.info(f"AI replied to {username}: {ai_reply}")
                except Exception as e:
                    logger.error(f"Failed to send AI reply: {e}")
            return


def main() -> None:
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return

    client = VoiceKeeperClient(config)

    token = config.get("token")
    if not token or token == "YOUR_USER_TOKEN_HERE" or token == "BOT_TOKEN":
        logger.error("Please configure a valid user token in config.json")
        return

    try:
        logger.info("Initializing connection to Discord...")
        # Start the client. This is a blocking call.
        client.run(token)
    except discord.LoginFailure:
        logger.error("Login failed. Improper token was passed or token is invalid.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()
