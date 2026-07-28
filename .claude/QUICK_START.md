# Quick Start Commands

---

## Development

```bash
# Bagimliliklar
pip install -r requirements.txt

# Botu calistir (panel: http://localhost:8080)
python main.py

# Testler (Discord baglantisi gerektirmez)
python tests/smoke_test.py

# Panel erisim anahtari uret
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## API'yi elle deneme

```bash
export KEY=...   # PANEL_API_KEY
curl -H "X-API-Key: $KEY" http://localhost:8080/api/status
curl -H "X-API-Key: $KEY" -X POST http://localhost:8080/api/control -d '{"action":"stop"}'
curl -N -H "X-API-Key: $KEY" http://localhost:8080/api/logs/stream
```

## Deploy

- **Bot**: Railway'e push (`Procfile` → `web: python main.py`, `$PORT` otomatik)
- **Panel**: `panel/` klasorune push → GitHub Actions Pages'e dagitir

---

**Last Updated**: 2026-07-28
