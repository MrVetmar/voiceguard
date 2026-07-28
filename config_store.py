"""
Merkezi konfigurasyon deposu.

Tasarim kurallari:
  * Sirlar (token, api key'ler) SADECE ortam degiskenlerinden veya mevcut
    config.json'dan okunur; panel uzerinden asla degistirilemez ve
    disk'e geri yazilirken korunur.
  * Operasyonel ayarlar (kanal ID'leri, zamanlama, master switch) panelden
    duzenlenebilir ve dogrulanir.
  * Yazma islemi atomiktir (tmp dosya + os.replace), boylece monitor loop
    yarim dosya okuyamaz.
  * Okuma islemi bellekte cache'lenir, dosya mtime degisirse yeniden yuklenir.
"""

import json
import os
import threading
from typing import Any, Dict

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.json")

# Panelden duzenlenebilen alanlar. Bunun disindaki her sey yok sayilir.
EDITABLE_KEYS = (
    "enabled",
    "guild_id",
    "voice_channel_id",
    "greeting_channel_id",
    "check_interval",
    "schedule",
)
EDITABLE_SCHEDULE_KEYS = ("enabled", "start_time", "end_time", "timezone")

# API cevaplarinda asla gorunmemesi gereken alanlar.
SECRET_KEYS = ("token", "nvidia_api_key", "panel_api_key")

# Discord snowflake ID'leri 2^53'u astigi icin JSON sayisi olarak gonderilirse
# JavaScript tarafinda hassasiyet kaybina ugrar (…377805 -> …378000).
# API'ye daima string olarak cikarlar; girerken tekrar int'e cevrilirler.
ID_KEYS = ("guild_id", "voice_channel_id", "greeting_channel_id")

MIN_CHECK_INTERVAL = 1
MAX_CHECK_INTERVAL = 300


class ConfigError(ValueError):
    """Konfigurasyon dogrulamasi basarisiz oldugunda firlatilir."""


def _defaults() -> Dict[str, Any]:
    return {
        "enabled": True,
        "guild_id": 0,
        "voice_channel_id": 0,
        "greeting_channel_id": 0,
        "check_interval": 5,
        "schedule": {
            "enabled": False,
            "start_time": "09:00",
            "end_time": "23:00",
            "timezone": "Europe/Istanbul",
        },
    }


def _as_int(value: Any, field: str, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ConfigError(f"'{field}' bir sayi olmali")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"'{field}' gecerli bir sayi degil: {value!r}")


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "evet")
    if value is None:
        return default
    return bool(value)


def _validate_time(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"'{field}' HH:MM formatinda olmali")
    text = value.strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ConfigError(f"'{field}' HH:MM formatinda olmali, alinan: {value!r}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise ConfigError(f"'{field}' HH:MM formatinda olmali, alinan: {value!r}")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(f"'{field}' gecersiz saat: {value!r}")
    return f"{hour:02d}:{minute:02d}"


def _validate_timezone(value: Any) -> str:
    text = (value or "").strip() if isinstance(value, str) else ""
    if not text:
        raise ConfigError("'timezone' bos birakilamaz")
    if ZoneInfo is not None:
        try:
            ZoneInfo(text)
        except Exception:
            raise ConfigError(f"Bilinmeyen saat dilimi: {text!r}")
    return text


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Ham sozlugu dogrulanmis operasyonel konfigurasyona cevirir."""
    base = _defaults()

    out: Dict[str, Any] = {
        "enabled": _as_bool(raw.get("enabled", base["enabled"]), base["enabled"]),
        "guild_id": _as_int(raw.get("guild_id"), "guild_id", base["guild_id"]),
        "voice_channel_id": _as_int(
            raw.get("voice_channel_id"), "voice_channel_id", base["voice_channel_id"]
        ),
        "greeting_channel_id": _as_int(
            raw.get("greeting_channel_id"), "greeting_channel_id", base["greeting_channel_id"]
        ),
    }

    interval = _as_int(raw.get("check_interval"), "check_interval", base["check_interval"])
    out["check_interval"] = max(MIN_CHECK_INTERVAL, min(MAX_CHECK_INTERVAL, interval))

    raw_schedule = raw.get("schedule")
    if not isinstance(raw_schedule, dict):
        raw_schedule = {}
    schedule_defaults = base["schedule"]
    schedule = {
        "enabled": _as_bool(
            raw_schedule.get("enabled", schedule_defaults["enabled"]), schedule_defaults["enabled"]
        ),
        "start_time": _validate_time(
            raw_schedule.get("start_time", schedule_defaults["start_time"]), "start_time"
        ),
        "end_time": _validate_time(
            raw_schedule.get("end_time", schedule_defaults["end_time"]), "end_time"
        ),
        "timezone": _validate_timezone(
            raw_schedule.get("timezone", schedule_defaults["timezone"])
        ),
    }
    out["schedule"] = schedule
    return out


def _read_file() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        # Bozuk dosya botu oldurmemeli; varsayilanlarla devam edilir.
        return {}


def _load_secrets(file_data: Dict[str, Any]) -> Dict[str, str]:
    """Sirlar once ortam degiskeninden, yoksa config.json'dan okunur."""
    return {
        "token": os.environ.get("DISCORD_TOKEN") or file_data.get("token", "") or "",
        "nvidia_api_key": os.environ.get("NVIDIA_API_KEY")
        or file_data.get("nvidia_api_key", "")
        or "",
        "panel_api_key": os.environ.get("PANEL_API_KEY")
        or file_data.get("panel_api_key", "")
        or "",
    }


def _env_overlay(file_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    config.json yoksa operasyonel ayarlar ortam degiskenlerinden gelir.
    Dosya varsa dosya kazanir (panel dosyaya yazar).
    """
    if file_data:
        return file_data

    env_schedule = {
        "enabled": os.environ.get("SCHEDULE_ENABLED", "false"),
        "start_time": os.environ.get("SCHEDULE_START", "09:00"),
        "end_time": os.environ.get("SCHEDULE_END", "23:00"),
        "timezone": os.environ.get("TIMEZONE", "Europe/Istanbul"),
    }
    return {
        "enabled": os.environ.get("BOT_ENABLED", "true"),
        "guild_id": os.environ.get("GUILD_ID", "0"),
        "voice_channel_id": os.environ.get("VOICE_CHANNEL_ID", "0"),
        "greeting_channel_id": os.environ.get("GREETING_CHANNEL_ID", "0"),
        "check_interval": os.environ.get("CHECK_INTERVAL", "5"),
        "schedule": env_schedule,
    }


class ConfigStore:
    """Thread-safe, mtime cache'li konfigurasyon deposu."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: Dict[str, Any] | None = None
        self._mtime: float | None = None

    def _file_mtime(self) -> float | None:
        try:
            return os.path.getmtime(CONFIG_PATH)
        except OSError:
            return None

    def get(self) -> Dict[str, Any]:
        """
        Guncel konfigurasyonu dondurur (sirlar dahil).
        Dosya disaridan degistirildiyse otomatik yeniden yukler.
        """
        with self._lock:
            mtime = self._file_mtime()
            if self._cache is None or mtime != self._mtime:
                file_data = _read_file()
                config = _normalize(_env_overlay(file_data))
                config.update(_load_secrets(file_data))
                self._cache = config
                self._mtime = mtime
            # Cagiran tarafin cache'i bozmamasi icin kopya donulur.
            copy = dict(self._cache)
            copy["schedule"] = dict(self._cache["schedule"])
            return copy

    def public(self) -> Dict[str, Any]:
        """Sirlari maskelenmis, panele gonderilmeye uygun kopya."""
        config = self.get()
        out = {k: v for k, v in config.items() if k not in SECRET_KEYS}
        # Snowflake'ler string olarak gider; 0 ise panelde alan bos gorunsun.
        for key in ID_KEYS:
            out[key] = str(out[key]) if out.get(key) else ""
        # Panelin "yapilandirilmis mi" gostergesi icin sadece boolean.
        out["has_ai_key"] = bool(config.get("nvidia_api_key"))
        out["has_token"] = bool(config.get("token"))
        return out

    def update(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Yalnizca EDITABLE_KEYS icindeki alanlari dogrular ve atomik yazar.
        Sirlar dosyada oldugu gibi korunur. Dogrulama basarisizsa
        ConfigError firlatir ve disk'e hicbir sey yazilmaz.
        """
        if not isinstance(patch, dict):
            raise ConfigError("Govde bir JSON nesnesi olmali")

        with self._lock:
            current = self.get()

            merged = {key: current[key] for key in EDITABLE_KEYS}
            merged["schedule"] = dict(current["schedule"])

            for key, value in patch.items():
                if key not in EDITABLE_KEYS:
                    continue  # Bilinmeyen / salt-okunur alanlar sessizce atlanir.
                if key == "schedule":
                    if not isinstance(value, dict):
                        raise ConfigError("'schedule' bir nesne olmali")
                    for sub_key, sub_value in value.items():
                        if sub_key in EDITABLE_SCHEDULE_KEYS:
                            merged["schedule"][sub_key] = sub_value
                else:
                    merged[key] = value

            validated = _normalize(merged)

            # Dosyadaki sirlari ve bilinmeyen alanlari koru.
            on_disk = _read_file()
            on_disk.update(validated)

            self._write_atomic(on_disk)
            self._cache = None  # Bir sonraki get() yeniden yukler.
            self._mtime = None

        return self.public()

    def _write_atomic(self, data: Dict[str, Any]) -> None:
        directory = os.path.dirname(os.path.abspath(CONFIG_PATH))
        tmp_path = f"{CONFIG_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_PATH)
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            # Windows dizin fsync'i desteklemez; os.replace zaten atomiktir.
            pass


store = ConfigStore()


def load_config() -> Dict[str, Any]:
    """Geriye donuk uyumluluk icin ince sarmalayici."""
    return store.get()
