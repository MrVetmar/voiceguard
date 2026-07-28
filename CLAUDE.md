# CLAUDE.md

**Quick-start guide for Claude Code - Complete details in linked docs**

---

## Project Overview

Discord ses kanalinda otomatik kalan, zamanlama destekli ve AI sohbet eden bot.
GitHub Pages'te barinan bir panelden uzaktan yonetilir.

```
GitHub Pages (panel/)  ──HTTPS + X-API-Key──▶  Railway (bot + aiohttp API)
```

**Tech Stack**: Python 3.12, discord.py-self, aiohttp, NVIDIA API (GLM 5.2),
vanilla JS panel, Railway + GitHub Actions/Pages

> ⚠️ `discord.py-self` bir kullanici hesabini otomatiklestirir; Discord ToS'a
> aykiridir ve hesap kapatilma riski tasir. Kalici cozum: gercek bot hesabi.

---

## Session Start Protocol ⚡

**MANDATORY** at start of each session:

```bash
# Load essential docs (~800 tokens - 2 min read)
✓ .claude/COMMON_MISTAKES.md      # ⚠️ CRITICAL - Read FIRST
✓ .claude/QUICK_START.md          # Essential commands
✓ .claude/ARCHITECTURE_MAP.md     # File locations
```

**At task completion:**
- Create completion doc in `.claude/completions/YYYY-MM-DD-task-name.md`
- Move session file to `.claude/sessions/archive/` (if created)

**⚠️ NEVER auto-load:**
- Files in `.claude/completions/` (0 token cost)
- Files in `.claude/sessions/` (0 token cost)
- Files in `docs/archive/` (0 token cost)

---

## Quick Start Commands

```bash
python main.py               # Botu calistir (panel: http://localhost:8080)
python tests/smoke_test.py   # Testler — Discord baglantisi gerektirmez
```

---

**Last Updated**: 2026-07-28
**Optimized with**: [Claude Token Optimizer](https://github.com/nadimtuhin/claude-token-optimizer)
