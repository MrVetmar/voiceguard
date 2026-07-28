import asyncio
import collections
import os
import random
import time
from datetime import datetime
from logger import logger

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None
    logger.error("openai package not installed. Run: pip install openai")

try:
    from openai import RateLimitError
except ImportError:
    RateLimitError = None


def _is_rate_limit(exc: Exception) -> bool:
    """Istisnanin 429 (hiz siniri) olup olmadigini guvenli sekilde anlar."""
    if RateLimitError is not None and isinstance(exc, RateLimitError):
        return True
    # SDK surumu farkliysa veya sarmalanmissa duruma bak.
    return getattr(exc, "status_code", None) == 429 or "429" in str(exc)


class ChatAI:
    """
    AI-powered conversational chat module using NVIDIA API.
    Remembers who it talked to, when, and keeps conversations natural and brief.
    """
    
    SYSTEM_PROMPT = """You are roleplaying as a real Turkish young person on Discord. You must ONLY write in Turkish. You are NOT an AI, you are a real human.

STRICT RULES:
1. Write ONLY in lowercase Turkish. No capital letters ever.
2. Keep responses to 3-8 words MAX. Never write long sentences.
3. Use casual Discord/internet Turkish slang naturally.
4. Never use formal language, never use "merhaba", never be polite like a bot.
5. Never use emojis excessively. Max 1 emoji per message, and only sometimes.
6. Never explain things. Never give advice. Just chat casually.
7. Never reveal you are an AI. You are a real person.

EXAMPLE CONVERSATIONS (copy this exact style):

User: hb
You: naber nasılsın

User: iyiyim sen
You: eh işte idare eder

User: ne yapıyon
You: bi şey yok takılıyom

User: bugün hava çok sıcaktı
You: harbi ya bunaldım

User: oyun oynuycak mısın
You: bilmiyom bakıcam sonra

User: tamam
You: hadi görüşürüz

IMPORTANT: Your responses must look EXACTLY like the examples above. Short, casual, lowercase, no punctuation except sometimes. If you write more than 8 words you have FAILED."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = None
        if AsyncOpenAI and api_key:
            self.client = AsyncOpenAI(
                base_url="https://integrate.api.nvidia.com/v1",
                api_key=api_key,
                # SDK varsayilani 2'dir: 429 alinca sessizce 2 kez daha dener,
                # yani hiz sinirina takilinca istek sayisi 3 katina cikar ve
                # sorunu buyutur. Yeniden deneme mantigini biz yonetiyoruz.
                max_retries=0,
            )
        # Active conversations: {user_id: ConversationData}
        self.conversations = {}
        # Per-user locks so a spamming user can't fan out parallel API calls
        self._locks = {}
        # Conversation timeout (10 minutes of inactivity)
        self.CONVERSATION_TIMEOUT = 600
        # Max exchanges before AI naturally wraps up
        self.MAX_EXCHANGES = 4

        # --- Hiz siniri korumasi ---
        # Kayan pencere: son 60 saniyedeki istek zamanlari.
        self.RATE_LIMIT_PER_MIN = int(os.environ.get("AI_RATE_LIMIT_PER_MIN", "15"))
        self._request_times = collections.deque()
        # 429 sonrasi devre kesici: ust uste her hatada bekleme suresi ikiye katlanir.
        self.COOLDOWN_BASE = 30
        self.COOLDOWN_MAX = 900
        self._cooldown_until = 0.0
        self._consecutive_429 = 0
        self._cooldown_logged = False

    # ------------------------------------------------------------ hiz siniri

    def _prune_requests(self) -> None:
        cutoff = time.time() - 60
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

    def _blocked_reason(self) -> str | None:
        """Istek atilmamasi gerekiyorsa sebebini dondurur, aksi halde None."""
        now = time.time()
        if now < self._cooldown_until:
            return f"429 sonrasi bekleme suresi ({int(self._cooldown_until - now)} sn kaldi)"
        self._prune_requests()
        if len(self._request_times) >= self.RATE_LIMIT_PER_MIN:
            return f"dakikalik istek siniri doldu ({self.RATE_LIMIT_PER_MIN}/dk)"
        return None

    def _note_rate_limited(self) -> None:
        """429 alindi: bekleme suresini ustel olarak artir."""
        self._consecutive_429 += 1
        wait = min(self.COOLDOWN_BASE * (2 ** (self._consecutive_429 - 1)), self.COOLDOWN_MAX)
        self._cooldown_until = time.time() + wait
        self._cooldown_logged = False
        logger.warning(
            f"NVIDIA API hiz siniri (429). {wait} saniye boyunca istek atilmayacak "
            f"(ust uste {self._consecutive_429}. kez)."
        )

    def _note_success(self) -> None:
        if self._consecutive_429:
            logger.info("NVIDIA API tekrar cevap veriyor, bekleme sifirlandi")
        self._consecutive_429 = 0
        self._cooldown_until = 0.0

    def ai_status(self) -> dict:
        """Panelin /api/status endpoint'i icin AI saglik ozeti."""
        now = time.time()
        self._prune_requests()
        return {
            "configured": self.client is not None,
            "rate_limited": now < self._cooldown_until,
            "cooldown_remaining": max(0, int(self._cooldown_until - now)),
            "requests_last_minute": len(self._request_times),
            "rate_limit_per_min": self.RATE_LIMIT_PER_MIN,
            "consecutive_429": self._consecutive_429,
        }

    def _get_conversation(self, user_id: int):
        """Get or return None for an active conversation."""
        conv = self.conversations.get(user_id)
        if conv and (time.time() - conv["last_activity"] > self.CONVERSATION_TIMEOUT):
            # Conversation expired
            self.end_conversation(user_id)
            return None
        return conv

    def prune_expired(self) -> int:
        """Drop timed-out conversations. Returns how many remain active."""
        now = time.time()
        expired = [
            uid
            for uid, conv in self.conversations.items()
            if now - conv["last_activity"] > self.CONVERSATION_TIMEOUT
        ]
        for uid in expired:
            self.end_conversation(uid)
        return len(self.conversations)

    def active_conversation_count(self) -> int:
        """Number of live conversations, used by the panel's status endpoint."""
        return self.prune_expired()

    def lock_for(self, user_id: int) -> asyncio.Lock:
        """Serialize a single user's requests so spam can't multiply API calls."""
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock

    def start_conversation(self, user_id: int, username: str):
        """Start a new conversation with a user."""
        now = time.time()
        current_time = datetime.now().strftime("%H:%M")
        self.conversations[user_id] = {
            "history": [],
            "username": username,
            "start_time": now,
            "last_activity": now,
            "exchange_count": 0,
            "current_time": current_time,
        }
        return self.conversations[user_id]

    def has_active_conversation(self, user_id: int) -> bool:
        """Check if a user has an active (non-expired) conversation."""
        return self._get_conversation(user_id) is not None

    async def get_response(self, user_id: int, username: str, user_message: str) -> str | None:
        """Generate an AI response for the user's message."""
        if not self.client:
            logger.error("AI client not initialized (missing API key or openai package)")
            return None

        blocked = self._blocked_reason()
        if blocked:
            if not self._cooldown_logged:
                logger.warning(f"AI istegi atlandi: {blocked}")
                self._cooldown_logged = True
            return None

        conv = self._get_conversation(user_id)
        if not conv:
            conv = self.start_conversation(user_id, username)

        conv["last_activity"] = time.time()
        conv["exchange_count"] += 1

        # Add user message to history
        conv["history"].append({"role": "user", "content": user_message})

        # Build the messages array with context
        context_note = f"[Speaking to: {username}. Message #{conv['exchange_count']}]"
        
        # If conversation is getting long, hint the AI to wrap up
        wrap_up = ""
        if conv["exchange_count"] >= self.MAX_EXCHANGES:
            wrap_up = "\n[END THE CONVERSATION NOW. Say something like 'neyse ben kaçıyom' or 'hadi görüşürüz' or 'sonra konuşuruz'. Keep it short.]"

        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT + f"\n\n{context_note}{wrap_up}"},
            *conv["history"]
        ]

        try:
            logger.info(f"Sending request to NVIDIA API (GLM 5.2)...")
            self._request_times.append(time.time())
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model="z-ai/glm-5.2",
                    messages=messages,
                    temperature=0.6,
                    max_tokens=40,
                ),
                timeout=30
            )
            
            choice = response.choices[0]
            ai_reply = None
            
            if choice.message.content:
                ai_reply = choice.message.content.strip()
                # Force lowercase and remove any quotes the model might add
                ai_reply = ai_reply.lower().strip('"').strip("'").strip("*")
                # If model wrote multiple lines, take only the first
                if "\n" in ai_reply:
                    ai_reply = ai_reply.split("\n")[0].strip()
            
            if not ai_reply:
                logger.warning(f"AI returned empty content. Full response: {response}")
                self._rollback_turn(conv)
                return None

            self._note_success()

            # Add AI response to history
            conv["history"].append({"role": "assistant", "content": ai_reply})

            # If we've exceeded max exchanges, end the conversation after this reply
            if conv["exchange_count"] >= self.MAX_EXCHANGES + 1:
                del self.conversations[user_id]
                logger.info(f"Conversation with {username} ended (max exchanges)")

            return ai_reply

        except asyncio.TimeoutError:
            logger.error("AI API request timed out (30s)")
            self._rollback_turn(conv)
            return None
        except Exception as e:
            if _is_rate_limit(e):
                self._note_rate_limited()
            else:
                logger.error(f"AI API error: {type(e).__name__}: {e}")
            self._rollback_turn(conv)
            return None

    @staticmethod
    def _rollback_turn(conv: dict) -> None:
        """
        Basarisiz bir turu gecmisten geri alir.

        Aksi halde kullanicinin mesaji gecmiste kalir ama karsiliginda asistan
        cevabi olmaz; birkac hatadan sonra gecmis ust uste 'user' mesajlarindan
        olusur ve modelin cevap kalitesi bozulur.
        """
        if conv["history"] and conv["history"][-1]["role"] == "user":
            conv["history"].pop()
        conv["exchange_count"] = max(0, conv["exchange_count"] - 1)

    def end_conversation(self, user_id: int):
        """Manually end a conversation and release its lock."""
        self.conversations.pop(user_id, None)
        lock = self._locks.get(user_id)
        if lock is not None and not lock.locked():
            del self._locks[user_id]
