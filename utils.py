"""
Geriye donuk uyumluluk sarmalayicisi.

Konfigurasyon mantigi config_store.py'ye tasindi. Yeni kod dogrudan
`from config_store import store` kullanmali.
"""

from typing import Any, Dict

from config_store import store


def load_config() -> Dict[str, Any]:
    return store.get()
