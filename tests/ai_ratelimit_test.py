"""
AI hiz siniri (429) korumasi testleri.

Calistirma:  python tests/ai_ratelimit_test.py
Gercek API cagrisi yapmaz; sahte istisna ve sahte istemci kullanir.
"""
import asyncio, os, sys, tempfile, time
os.environ["CONFIG_PATH"] = os.path.join(tempfile.mkdtemp(), "config.json")
os.environ["AI_RATE_LIMIT_PER_MIN"] = "3"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chat_ai import ChatAI, _is_rate_limit
from openai import RateLimitError
import httpx

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok  " if cond else "  FAIL") + f"  {name}" + (f"  -> {extra}" if extra and not cond else ""))

def make_429():
    req = httpx.Request("POST", "https://integrate.api.nvidia.com/v1/chat/completions")
    resp = httpx.Response(429, request=req, json={"status": 429, "title": "Too Many Requests"})
    return RateLimitError("Error code: 429", response=resp, body=None)

print("[429 tespiti]")
check("RateLimitError taniniyor", _is_rate_limit(make_429()))
check("metinden 429 taniniyor", _is_rate_limit(Exception("Error code: 429 - Too Many Requests")))
check("alakasiz hata 429 sayilmiyor", not _is_rate_limit(ValueError("bir sey oldu")))

print("\n[SDK sessiz yeniden deneme]")
ai = ChatAI("sahte-anahtar")
check("max_retries = 0", ai.client.max_retries == 0, ai.client.max_retries)

print("\n[dakikalik istek siniri]")
ai2 = ChatAI("sahte-anahtar")
check("limit env'den okundu (3/dk)", ai2.RATE_LIMIT_PER_MIN == 3, ai2.RATE_LIMIT_PER_MIN)
for i in range(3):
    ai2._request_times.append(time.time())
check("limit dolunca istek engelleniyor", ai2._blocked_reason() is not None, ai2._blocked_reason())
ai2._request_times.clear()
check("pencere bosalinca tekrar serbest", ai2._blocked_reason() is None)

print("\n[devre kesici / ustel bekleme]")
ai3 = ChatAI("sahte-anahtar")
check("baslangicta engel yok", ai3._blocked_reason() is None)
waits = []
for i in range(4):
    ai3._note_rate_limited()
    waits.append(round(ai3._cooldown_until - time.time()))
check("bekleme ikiye katlaniyor (30/60/120/240)", waits == [30, 60, 120, 240], waits)
check("429 sonrasi istek engelli", ai3._blocked_reason() is not None)
check("panel durumu hiz sinirini gosteriyor", ai3.ai_status()["rate_limited"] is True, ai3.ai_status())
ai3._note_success()
check("basarili istek beklemeyi sifirliyor",
      ai3._blocked_reason() is None and ai3._consecutive_429 == 0)

ai4 = ChatAI("sahte-anahtar")
for i in range(20):
    ai4._note_rate_limited()
check("bekleme ust sinirda duruyor (900 sn)",
      round(ai4._cooldown_until - time.time()) == 900, round(ai4._cooldown_until - time.time()))

print("\n[basarisiz turun geri alinmasi]")
conv = {"history": [{"role": "user", "content": "selam"}], "exchange_count": 1}
ChatAI._rollback_turn(conv)
check("basarisiz kullanici mesaji gecmisten silindi", conv["history"] == [], conv)
check("exchange_count geri alindi", conv["exchange_count"] == 0, conv)
conv2 = {"history": [{"role": "assistant", "content": "naber"}], "exchange_count": 2}
ChatAI._rollback_turn(conv2)
check("asistan mesajina dokunulmuyor", len(conv2["history"]) == 1, conv2)

print("\n[hiz siniriyken API cagrilmiyor]")
async def t():
    ai5 = ChatAI("sahte-anahtar")
    called = []
    class FakeCompletions:
        async def create(self, **kw): called.append(kw); raise AssertionError("cagrilmamaliydi")
    ai5.client.chat.completions = FakeCompletions()
    ai5._note_rate_limited()
    out = await ai5.get_response(1, "test", "selam")
    check("bekleme sirasinda cevap None", out is None)
    check("bekleme sirasinda API'ye hic gidilmedi", called == [], called)
asyncio.run(t())

print(f"\n{'='*50}\n{len(PASS)} gecti, {len(FAIL)} kaldi")
if FAIL: print("Basarisiz:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
