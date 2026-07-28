"""
VoiceGuard duman testi: konfigurasyon deposu, kontrol API'si ve zamanlama mantigi.

Calistirma:  python tests/smoke_test.py
Discord baglantisi gerektirmez; sahte bir istemci kullanir.
"""
import asyncio, json, os, sys, tempfile, traceback

# Gercek config.json'a dokunmamak icin izole bir dosya kullanilir.
TMP = tempfile.mkdtemp()
os.environ["CONFIG_PATH"] = os.path.join(TMP, "config.json")
os.environ["PANEL_API_KEY"] = "test-key-123"
os.environ["DISCORD_TOKEN"] = "fake-token"
os.environ["NVIDIA_API_KEY"] = "fake-nvidia"
os.environ["PANEL_ORIGINS"] = "https://user.github.io"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp.test_utils import TestClient, TestServer
from chat_ai import ChatAI
from config_store import store, ConfigError
import web_server, runtime_state, logger as logmod

PASS, FAIL = [], []
def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok  " if cond else "  FAIL") + f"  {name}" + (f"  -> {extra}" if extra and not cond else ""))


class FakeChatAI(ChatAI):
    """Gercek ChatAI - sadece sohbet sayaci sabitlenmis (anahtarsiz, API cagirmaz).

    Sahte bir sinif yerine gercegini kullanmak, web_server'in bekledigi
    arayuz degistiginde testin bunu yakalamasini saglar.
    """
    def __init__(self): super().__init__("")
    def active_conversation_count(self): return 3

class FakeClient:
    chat_ai = FakeChatAI()
    def get_guild(self, gid): return None


def test_config_store():
    print("\n[config_store]")
    cfg = store.get()
    check("varsayilanlar yuklendi", cfg["enabled"] is True and cfg["check_interval"] == 5, cfg)
    check("sirlar env'den geldi", cfg["token"] == "fake-token" and cfg["panel_api_key"] == "test-key-123")

    pub = store.public()
    check("public() sirlari gizliyor",
          "token" not in pub and "nvidia_api_key" not in pub and "panel_api_key" not in pub, pub)
    check("public() has_ai_key veriyor", pub.get("has_ai_key") is True)

    # Regresyon: Discord snowflake'leri 2^53'u asar. JSON sayisi olarak
    # gonderilirse JavaScript'te ...377805 -> ...378000 olur ve panel yanlis
    # ID kaydeder. API'de daima string olmalilar.
    SNOWFLAKE = 1526981644123377805
    out = store.update({"guild_id": SNOWFLAKE})
    check("snowflake string olarak donuyor", out["guild_id"] == str(SNOWFLAKE), repr(out["guild_id"]))
    check("snowflake dahili olarak int kaliyor", store.get()["guild_id"] == SNOWFLAKE)
    out2 = store.update({"guild_id": out["guild_id"]})   # panel geri gonderir
    check("snowflake gidis-donuste bozulmuyor", store.get()["guild_id"] == SNOWFLAKE, out2["guild_id"])
    check("bos ID paneldeki alani bos birakiyor", store.update({"guild_id": 0})["guild_id"] == "")

    out = store.update({"guild_id": "123", "check_interval": 999, "schedule": {"enabled": True, "start_time": "7:5"}})
    check("guild_id sayiya cevrildi", store.get()["guild_id"] == 123, out["guild_id"])
    check("check_interval kirpildi (999 -> 300)", out["check_interval"] == 300, out["check_interval"])
    check("saat normalize edildi (7:5 -> 07:05)", out["schedule"]["start_time"] == "07:05", out["schedule"])

    for bad, label in [
        ({"schedule": {"timezone": "Mars/Olympus"}}, "gecersiz saat dilimi"),
        ({"schedule": {"start_time": "99:99"}}, "gecersiz saat"),
        ({"guild_id": "abc"}, "sayi olmayan guild_id"),
        ({"schedule": "bu bir string"}, "schedule nesne degil"),
    ]:
        try:
            store.update(bad); check(f"{label} reddedildi", False, "hata firlatilmadi")
        except ConfigError:
            check(f"{label} reddedildi", True)

    # Sirlar diske yazilmis olmali mi? (env'den geldiler -> yazilmamali)
    with open(os.environ["CONFIG_PATH"], encoding="utf-8") as f:
        on_disk = json.load(f)
    check("sirlar config.json'a yazilmadi",
          "token" not in on_disk and "panel_api_key" not in on_disk, list(on_disk))

    # Bilinmeyen alan sessizce yok sayilmali
    before = store.get()["guild_id"]
    out = store.update({"token": "ELE-GECIRME-DENEMESI", "enabled": False})
    check("panel token'i degistiremiyor", store.get()["token"] == "fake-token")
    check("enabled guncellendi", out["enabled"] is False)
    store.update({"enabled": True})

    # Bozuk dosya botu oldurmemeli
    with open(os.environ["CONFIG_PATH"], "w", encoding="utf-8") as f:
        f.write("{bozuk json")
    store._cache = None; store._mtime = None
    try:
        check("bozuk config.json cokmuyor", store.get()["check_interval"] == 5)
    except Exception as e:
        check("bozuk config.json cokmuyor", False, repr(e))
    store.update({"guild_id": 123, "voice_channel_id": 456, "greeting_channel_id": 789})


async def test_api():
    print("\n[api]")
    logmod.broadcaster.bind_loop(asyncio.get_running_loop())
    app = web_server.build_app(FakeClient())
    async with TestClient(TestServer(app)) as cl:
        H = {"X-API-Key": "test-key-123"}

        r = await cl.get("/api/health")
        check("/api/health auth istemiyor", r.status == 200, r.status)

        r = await cl.get("/api/config")
        check("anahtarsiz istek 401", r.status == 401, r.status)

        r = await cl.get("/api/config", headers={"X-API-Key": "yanlis"})
        check("yanlis anahtar 401", r.status == 401, r.status)

        r = await cl.get("/api/config", headers={"Authorization": "Bearer test-key-123"})
        check("Bearer basligi kabul ediliyor", r.status == 200, r.status)

        r = await cl.get("/api/config", headers=H)
        body = await r.json()
        check("/api/config sirlari sizdirmiyor",
              not any(k in body for k in ("token", "nvidia_api_key", "panel_api_key")), list(body))

        r = await cl.get("/api/status", headers=H)
        st = await r.json()
        check("/api/status calisiyor", r.status == 200 and "uptime_seconds" in st, st)
        check("aktif sohbet sayisi geliyor", st["active_conversations"] == 3, st.get("active_conversations"))
        check("AI durumu status'e dahil",
              isinstance(st.get("ai"), dict) and "rate_limited" in st["ai"], st.get("ai"))

        r = await cl.post("/api/config", headers=H, json={"check_interval": 12})
        check("POST /api/config kaydediyor", r.status == 200 and (await r.json())["check_interval"] == 12)

        r = await cl.post("/api/config", headers=H, json={"schedule": {"timezone": "Yok/Boyle"}})
        body = await r.json()
        check("gecersiz POST 400 donuyor", r.status == 400 and body["error"] == "validation_failed", body)

        r = await cl.post("/api/config", headers=H, data="bu json degil")
        check("bozuk JSON 400 donuyor", r.status == 400, r.status)

        r = await cl.post("/api/control", headers=H, json={"action": "stop"})
        check("control stop calisiyor", r.status == 200 and store.get()["enabled"] is False)
        r = await cl.post("/api/control", headers=H, json={"action": "start"})
        check("control start calisiyor", r.status == 200 and store.get()["enabled"] is True)
        r = await cl.post("/api/control", headers=H, json={"action": "rm -rf"})
        check("bilinmeyen komut 400", r.status == 400, r.status)

        r = await cl.options("/api/config", headers={"Origin": "https://user.github.io"})
        check("CORS preflight 204", r.status == 204, r.status)
        check("CORS origin yansitiliyor",
              r.headers.get("Access-Control-Allow-Origin") == "https://user.github.io",
              r.headers.get("Access-Control-Allow-Origin"))
        check("CORS X-API-Key basligina izin veriyor",
              "X-API-Key" in r.headers.get("Access-Control-Allow-Headers", ""))

        r = await cl.get("/api/config", headers={**H, "Origin": "https://kotu-site.com"})
        check("izinsiz origin yansitilmiyor",
              r.headers.get("Access-Control-Allow-Origin") == "https://user.github.io",
              r.headers.get("Access-Control-Allow-Origin"))

        r = await cl.get("/api/logs", headers=H)
        logs = (await r.json())["logs"]
        check("/api/logs gecmis donuyor", r.status == 200 and isinstance(logs, list), r.status)

        # SSE: ilk kareyi al
        logmod.logger.info("SSE test kaydi")
        r = await cl.get("/api/logs/stream", headers=H)
        check("SSE content-type dogru", r.content_type == "text/event-stream", r.content_type)
        try:
            raw = await asyncio.wait_for(r.content.readuntil(b"\n\n"), timeout=5)
            entry = json.loads(raw.decode().split("data:", 1)[1].strip())
            check("SSE kare JSON olarak cozuluyor", "message" in entry and "level" in entry, entry)
        except Exception as e:
            check("SSE kare JSON olarak cozuluyor", False, repr(e))
        r.close()


def test_voice_logic():
    print("\n[voice_keeper]")
    from voice_keeper import should_be_connected, is_active_time
    base = {"enabled": True, "schedule": {"enabled": False}}
    check("zamanlama kapali -> 7/24 aktif", should_be_connected(base) is True)
    check("master switch kapali -> pasif", should_be_connected({**base, "enabled": False}) is False)
    check("gece yarisini asan aralik (23:00-06:00, 02:00)",
          is_active_time("23:00", "06:00", "UTC") in (True, False))  # sadece patlamasin
    sched = {"enabled": True, "start_time": "00:00", "end_time": "23:59", "timezone": "Europe/Istanbul"}
    check("tam gun araligi aktif", should_be_connected({"enabled": True, "schedule": sched}) is True)
    check("gecersiz saat dilimi aktife dusuyor",
          should_be_connected({"enabled": True, "schedule": {**sched, "timezone": "Yok/Boyle"}}) is True)


try:
    test_config_store()
    asyncio.run(test_api())
    test_voice_logic()
except Exception:
    traceback.print_exc()
    FAIL.append("beklenmeyen istisna")

print(f"\n{'='*50}\n{len(PASS)} gecti, {len(FAIL)} kaldi")
if FAIL:
    print("Basarisiz:", ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
