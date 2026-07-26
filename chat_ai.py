import asyncio
import random
import time
from datetime import datetime
from logger import logger

try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None
    logger.error("openai package not installed. Run: pip install openai")


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
                api_key=api_key
            )
        # Active conversations: {user_id: ConversationData}
        self.conversations = {}
        # Conversation timeout (10 minutes of inactivity)
        self.CONVERSATION_TIMEOUT = 600
        # Max exchanges before AI naturally wraps up
        self.MAX_EXCHANGES = 4

    def _get_conversation(self, user_id: int):
        """Get or return None for an active conversation."""
        conv = self.conversations.get(user_id)
        if conv and (time.time() - conv["last_activity"] > self.CONVERSATION_TIMEOUT):
            # Conversation expired
            del self.conversations[user_id]
            return None
        return conv

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
                return None
            
            # Add AI response to history
            conv["history"].append({"role": "assistant", "content": ai_reply})

            # If we've exceeded max exchanges, end the conversation after this reply
            if conv["exchange_count"] >= self.MAX_EXCHANGES + 1:
                del self.conversations[user_id]
                logger.info(f"Conversation with {username} ended (max exchanges)")

            return ai_reply

        except asyncio.TimeoutError:
            logger.error("AI API request timed out (30s)")
            return None
        except Exception as e:
            logger.error(f"AI API error: {type(e).__name__}: {e}")
            return None

    def end_conversation(self, user_id: int):
        """Manually end a conversation."""
        if user_id in self.conversations:
            del self.conversations[user_id]
