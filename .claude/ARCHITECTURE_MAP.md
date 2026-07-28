# Architecture Map

---

## Directory Structure

```
VoiceGuard/
├── main.py               # Discord istemcisi, on_message (selamlasma + AI yonlendirme)
├── voice_keeper.py       # monitor_loop: ses baglantisini kurar/korur, zamanlama
├── chat_ai.py            # ChatAI: konusma state'i, NVIDIA API cagrisi, persona
├── config_store.py       # Tek konfigurasyon kaynagi: dogrulama, atomik yazma, cache
├── runtime_state.py      # Canli durum (baglanti, uptime, son hata) -> /api/status
├── web_server.py         # aiohttp kontrol API'si: auth, CORS, SSE log akisi
├── logger.py             # Logger + halka tampon + SSE yayinci (broadcaster)
├── utils.py              # Geriye donuk uyumluluk sarmalayicisi (-> config_store)
├── panel/index.html      # GitHub Pages'te yayinlanan kontrol paneli
├── tests/smoke_test.py   # Discord'suz duman testi
└── .github/workflows/pages.yml   # Paneli GitHub Pages'e dagitir
```

## Veri akisi

```
panel/index.html ──HTTPS+X-API-Key──▶ web_server.py ──▶ config_store.store
                                                              │
                     voice_keeper.monitor_loop ◀── store.get()┘  (mtime cache)
                     main.on_message          ◀── store.get()

logger.logger ──▶ broadcaster (halka tampon) ──SSE──▶ panel canli log
voice_keeper / main ──▶ runtime_state ──▶ /api/status ──▶ panel durum kartlari
```

## Key File Locations

- **Configuration**: `config_store.py` (mantik), `config.json` (operasyonel ayarlar,
  git'te yok), ortam degiskenleri (sirlar — tek kaynak)
- **Main entry**: `main.py`
- **Tests**: `tests/smoke_test.py`
- **API endpoint'leri**: `web_server.py` icindeki `build_app()`

## Sinirlar

- Sirlar (`token`, `nvidia_api_key`, `panel_api_key`) SADECE env'den okunur;
  panel bunlari goremez, `config.json`'a yazilmaz.
- Panelden duzenlenebilir alanlar `config_store.EDITABLE_KEYS` ile sinirlidir.
- Discord ID'leri API'de daima **string**'dir (`config_store.ID_KEYS`),
  dahili olarak int.

---

**Last Updated**: 2026-07-28
