import asyncio
import random
import re
import time

import discord

from chat_ai import ChatAI
from config_store import store
from logger import broadcaster, logger
import runtime_state
from voice_keeper import monitor_loop
from web_server import start_web_server

GREETING_PATTERN = re.compile(
    r"\b(s\.a|sa|selam|selamun aleykum|selamun aleyk[uü]m|selam[iı]n aleyk[uü]m)\b",
    re.IGNORECASE,
)
HB_PATTERN = re.compile(
    r"\b(hb|ho[sş] ?bulduk|ho[sş] ?buldum)\b",
    re.IGNORECASE,
)


class VoiceGuardClient(discord.Client):
    """Ses kanalinda kalma, selamlasma ve AI sohbetini yoneten Discord istemcisi."""

    GREET_COOLDOWN = 900  # Ayni kullaniciya tekrar selam vermeden once beklenen sure (sn)
    GREET_CACHE_LIMIT = 1000

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.monitor_task = None
        self.web_runner = None
        self.greeted_users = {}  # {user_id: son_selam_zamani}
        self.chat_ai = ChatAI(config.get("nvidia_api_key", ""))

    async def setup_hook(self) -> None:
        """Gateway baglantisindan once arka plan gorevlerini baslatir."""
        broadcaster.bind_loop(asyncio.get_running_loop())
        self.monitor_task = self.loop.create_task(monitor_loop(self))
        self.web_runner = await start_web_server(self)

    async def close(self) -> None:
        """Kapanista web sunucusunu ve izleyici gorevini duzgunce sonlandirir."""
        if self.monitor_task:
            self.monitor_task.cancel()
        if self.web_runner:
            await self.web_runner.cleanup()
        await super().close()

    async def on_ready(self) -> None:
        logger.info(f"Discord'a baglanildi: {self.user} (ID: {self.user.id})")
        runtime_state.mark_ready(str(self.user), self.user.id)

    async def on_resumed(self) -> None:
        logger.info("Oturum yeniden kuruldu (Gateway reconnect)")
        runtime_state.mark_resumed()

    async def on_disconnect(self) -> None:
        logger.warning("Discord Gateway baglantisi koptu")
        runtime_state.mark_disconnected()

    # ---------------------------------------------------------------- mesajlar

    def _should_greet(self, user_id: int) -> bool:
        """Cooldown kontrolu; ayni zamanda sisen onbellegi budar."""
        now = time.time()
        if now - self.greeted_users.get(user_id, 0) < self.GREET_COOLDOWN:
            return False

        if len(self.greeted_users) >= self.GREET_CACHE_LIMIT:
            cutoff = now - self.GREET_COOLDOWN
            self.greeted_users = {
                uid: ts for uid, ts in self.greeted_users.items() if ts > cutoff
            }

        self.greeted_users[user_id] = now
        return True

    async def _reply_naturally(self, message: discord.Message, text: str) -> None:
        """Insan temposuna yakin bir gecikme ve 'yaziyor' gostergesiyle cevap verir."""
        await asyncio.sleep(random.uniform(0.5, 1.2))
        async with message.channel.typing():
            await asyncio.sleep(max(0.6, min(len(text) * 0.04, 2.0)))
        try:
            await message.reply(text, mention_author=False)
        except Exception as exc:
            logger.error(f"Cevap gonderilemedi: {exc}")
            runtime_state.record_error(f"reply: {exc}")

    async def _handle_ai_turn(self, message: discord.Message, fresh: bool) -> None:
        user_id = message.author.id
        username = message.author.display_name or message.author.name

        lock = self.chat_ai.lock_for(user_id)
        if lock.locked():
            # Kullanici cevap beklerken tekrar yazdi; ust uste API cagrisi yapma.
            return

        async with lock:
            if fresh:
                self.chat_ai.start_conversation(user_id, username)
            reply = await self.chat_ai.get_response(user_id, username, message.content.strip())

        if reply:
            await self._reply_naturally(message, reply)
            logger.info(f"AI cevabi ({username}): {reply}")

    async def on_message(self, message: discord.Message) -> None:
        # Kendi mesajlarimizi ve diger botlari yok say (iki bot sonsuz dongu yapmasin).
        if message.author.id == self.user.id or message.author.bot:
            return

        config = store.get()
        greeting_channel_id = config.get("greeting_channel_id")
        if not greeting_channel_id or message.channel.id != greeting_channel_id:
            return

        username = message.author.display_name or message.author.name
        content = message.content.strip()

        # 1) Selamlasma
        if GREETING_PATTERN.search(content):
            if not self._should_greet(message.author.id):
                return
            logger.info(f"Selam algilandi: {username}")
            await self._reply_naturally(message, "as hoş geldin")
            return

        # 2) "hb" -> yeni AI sohbeti baslat
        if HB_PATTERN.search(content):
            logger.info(f"'hb' algilandi ({username}), AI sohbeti basliyor")
            await self._handle_ai_turn(message, fresh=True)
            return

        # 3) Devam eden AI sohbeti
        if self.chat_ai.has_active_conversation(message.author.id):
            await self._handle_ai_turn(message, fresh=False)


def main() -> None:
    try:
        config = store.get()
    except Exception as exc:
        logger.error(f"Konfigurasyon yuklenemedi: {exc}")
        return

    token = config.get("token")
    if not token or token in ("YOUR_USER_TOKEN_HERE", "YOUR_DISCORD_USER_TOKEN_HERE", "BOT_TOKEN"):
        logger.error("Gecerli bir token bulunamadi. DISCORD_TOKEN ortam degiskenini ayarlayin.")
        return

    client = VoiceGuardClient(config)
    try:
        logger.info("Discord baglantisi baslatiliyor...")
        client.run(token)
    except discord.LoginFailure:
        logger.error("Giris basarisiz. Token gecersiz.")
    except Exception as exc:
        logger.error(f"Beklenmeyen hata: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
