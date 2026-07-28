"""
VoiceGuard kontrol API'si (aiohttp).

Panel GitHub Pages'te statik olarak barinir ve buraya capraz-kaynak (CORS)
istek atar. Kimlik dogrulama X-API-Key basligi ile yapilir; anahtar
PANEL_API_KEY ortam degiskeninden gelir.

Endpoint'ler
------------
  GET  /                  -> panel/index.html (yedek arayuz)
  GET  /api/health        -> auth yok, ayakta mi kontrolu
  GET  /api/config        -> ayarlar (sirlar maskeli)
  POST /api/config        -> ayarlari dogrulayarak gunceller
  GET  /api/status        -> canli durum
  POST /api/control       -> {"action": "start" | "stop" | "reconnect"}
  GET  /api/logs          -> son N log kaydi
  GET  /api/logs/stream   -> SSE canli log akisi
"""

import asyncio
import hmac
import json
import os
import time
from typing import Any, Awaitable, Callable, Optional

from aiohttp import web

from config_store import ConfigError, store
from logger import broadcaster, logger
import runtime_state

VERSION = "2.0.0"

# SSE baglantisini vekil sunucularin kesmemesi icin heartbeat araligi.
SSE_HEARTBEAT_SECONDS = 25

_PUBLIC_PATHS = {"/", "/api/health"}


def _allowed_origins() -> list[str]:
    raw = os.environ.get("PANEL_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ["*"]
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


def _resolve_origin(request: web.Request) -> str:
    """Istegin Origin'ine gore dondurulecek CORS degerini secer."""
    allowed = _allowed_origins()
    if allowed == ["*"]:
        return "*"
    origin = (request.headers.get("Origin") or "").rstrip("/")
    return origin if origin in allowed else allowed[0]


def _apply_cors(request: web.Request, response: web.StreamResponse) -> None:
    response.headers["Access-Control-Allow-Origin"] = _resolve_origin(request)
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, Authorization"
    response.headers["Access-Control-Max-Age"] = "86400"
    response.headers["Vary"] = "Origin"


def _presented_key(request: web.Request) -> str:
    key = request.headers.get("X-API-Key")
    if key:
        return key.strip()
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


@web.middleware
async def cors_middleware(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    if request.method == "OPTIONS":
        response = web.Response(status=204)
        _apply_cors(request, response)
        return response
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        _apply_cors(request, exc)
        raise
    _apply_cors(request, response)
    return response


@web.middleware
async def auth_middleware(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    if request.method == "OPTIONS" or request.path in _PUBLIC_PATHS:
        return await handler(request)

    expected = store.get().get("panel_api_key", "")
    if not expected:
        # Anahtar tanimlanmadan API'yi acmak paneli herkese acik birakir.
        return web.json_response(
            {
                "error": "panel_api_key_not_set",
                "detail": "PANEL_API_KEY ortam degiskeni tanimli degil. "
                "API guvenlik nedeniyle kilitli.",
            },
            status=503,
        )

    presented = _presented_key(request)
    if not presented or not hmac.compare_digest(presented, expected):
        return web.json_response({"error": "unauthorized"}, status=401)

    return await handler(request)


# --------------------------------------------------------------------------
# Handler'lar
# --------------------------------------------------------------------------


async def handle_index(request: web.Request) -> web.StreamResponse:
    """Yedek arayuz: GitHub Pages erisilemezse bot kendi panelini sunar."""
    panel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel", "index.html")
    try:
        with open(panel_path, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")
    except FileNotFoundError:
        return web.Response(text="panel/index.html bulunamadi", status=404)


async def handle_health(request: web.Request) -> web.StreamResponse:
    config = store.get()
    return web.json_response(
        {
            "ok": True,
            "version": VERSION,
            "ready": bool(runtime_state.snapshot()["discord"]["ready"]),
            "auth_required": bool(config.get("panel_api_key")),
        }
    )


async def handle_get_config(request: web.Request) -> web.StreamResponse:
    return web.json_response(store.public())


async def handle_post_config(request: web.Request) -> web.StreamResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid_json"}, status=400)

    try:
        updated = store.update(payload)
    except ConfigError as exc:
        return web.json_response({"error": "validation_failed", "detail": str(exc)}, status=400)
    except OSError as exc:
        logger.error(f"Konfigurasyon yazilamadi: {exc}")
        return web.json_response({"error": "write_failed", "detail": str(exc)}, status=500)

    logger.info("Konfigurasyon panel uzerinden guncellendi")
    runtime_state.record_action("config_update")
    return web.json_response(updated)


async def handle_status(request: web.Request) -> web.StreamResponse:
    client = request.app["client"]
    active = 0
    ai_status = None
    chat_ai = getattr(client, "chat_ai", None)
    if chat_ai is not None:
        active = chat_ai.active_conversation_count()
        ai_status = chat_ai.ai_status()

    snapshot = runtime_state.snapshot(active_conversations=active)
    snapshot["ai"] = ai_status
    snapshot["config"] = store.public()
    snapshot["log_subscribers"] = broadcaster.subscriber_count
    return web.json_response(snapshot)


async def handle_control(request: web.Request) -> web.StreamResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid_json"}, status=400)

    action = (payload or {}).get("action")
    client = request.app["client"]

    if action in ("start", "stop"):
        enabled = action == "start"
        try:
            store.update({"enabled": enabled})
        except (ConfigError, OSError) as exc:
            return web.json_response({"error": "write_failed", "detail": str(exc)}, status=500)
        logger.info(f"Panel komutu: bot {'baslatildi' if enabled else 'durduruldu'}")
        runtime_state.record_action(action)
        return web.json_response({"status": "ok", "enabled": enabled})

    if action == "reconnect":
        from voice_keeper import force_reconnect

        logger.info("Panel komutu: yeniden baglanma tetiklendi")
        runtime_state.record_action("reconnect")
        await force_reconnect(client, store.get())
        return web.json_response({"status": "ok"})

    return web.json_response(
        {"error": "unknown_action", "detail": "Gecerli degerler: start, stop, reconnect"},
        status=400,
    )


async def handle_logs(request: web.Request) -> web.StreamResponse:
    try:
        limit = int(request.query.get("limit", "200"))
    except ValueError:
        limit = 200
    limit = max(1, min(limit, 500))
    return web.json_response({"logs": broadcaster.history(limit)})


async def handle_log_stream(request: web.Request) -> web.StreamResponse:
    """
    Server-Sent Events akisi.

    Panel tarafinda EventSource yerine fetch + ReadableStream kullaniliyor;
    boylece API anahtari URL yerine baslikta tasinabiliyor.
    """
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    _apply_cors(request, response)
    await response.prepare(request)

    queue = broadcaster.subscribe()
    try:
        for entry in broadcaster.history(50):
            await response.write(f"data: {json.dumps(entry)}\n\n".encode("utf-8"))

        while True:
            try:
                entry = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                await response.write(f"data: {json.dumps(entry)}\n\n".encode("utf-8"))
            except asyncio.TimeoutError:
                await response.write(b": heartbeat\n\n")
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning(f"Log akisi kesildi: {type(exc).__name__}: {exc}")
    finally:
        broadcaster.unsubscribe(queue)

    return response


def build_app(client: Any) -> web.Application:
    app = web.Application(middlewares=[cors_middleware, auth_middleware])
    app["client"] = client
    app.add_routes(
        [
            web.get("/", handle_index),
            web.get("/api/health", handle_health),
            web.get("/api/config", handle_get_config),
            web.post("/api/config", handle_post_config),
            web.get("/api/status", handle_status),
            web.post("/api/control", handle_control),
            web.get("/api/logs", handle_logs),
            web.get("/api/logs/stream", handle_log_stream),
            web.options("/{tail:.*}", lambda request: web.Response(status=204)),
        ]
    )
    return app


async def start_web_server(client: Any) -> web.AppRunner:
    """API sunucusunu baslatir ve runner'i dondurur (kapanista temizlik icin)."""
    app = build_app(client)
    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    if not store.get().get("panel_api_key"):
        logger.warning(
            "PANEL_API_KEY tanimli degil! API kilitli calisiyor; "
            "panelden yonetim icin bu degiskeni ayarlayin."
        )
    logger.info(f"Kontrol API'si :{port} portunda basladi (CORS: {', '.join(_allowed_origins())})")
    return runner
