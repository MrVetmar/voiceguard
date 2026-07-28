"""
Uygulama logger'i + panelin canli log akisini besleyen halka tampon.

Log kayitlari hem stdout'a (Railway loglari) hem de bellekteki bir deque'e
yazilir. Panel once /api/logs ile son N kaydi ceker, ardindan
/api/logs/stream (SSE) uzerinden yeni kayitlari canli alir.
"""

import asyncio
import collections
import logging
import sys
import time
from typing import Any, Deque, Dict, List, Optional, Set

LOG_BUFFER_SIZE = 500
SUBSCRIBER_QUEUE_SIZE = 200


class LogBroadcaster(logging.Handler):
    """
    Log kayitlarini halka tamponda tutar ve abone olan SSE istemcilerine dagitir.

    logging cagrilari baska thread'lerden gelebilecegi icin kuyruga yazma
    daima loop.call_soon_threadsafe uzerinden yapilir.
    """

    def __init__(self, maxlen: int = LOG_BUFFER_SIZE) -> None:
        super().__init__()
        self._buffer: Deque[Dict[str, Any]] = collections.deque(maxlen=maxlen)
        self._subscribers: Set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._seq = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Botun event loop'unu kaydeder; thread-safe yayin icin gerekli."""
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "at": record.created,
                "level": record.levelname,
                "message": record.getMessage(),
            }
            self._buffer.append(entry)
            self._publish(entry)
        except Exception:  # pragma: no cover - logging asla patlamamali
            self.handleError(record)

    def _publish(self, entry: Dict[str, Any]) -> None:
        if not self._subscribers:
            return
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        for queue in list(self._subscribers):
            try:
                loop.call_soon_threadsafe(self._offer, queue, entry)
            except RuntimeError:
                # Loop kapaniyor; sessizce gec.
                pass

    @staticmethod
    def _offer(queue: asyncio.Queue, entry: Dict[str, Any]) -> None:
        try:
            queue.put_nowait(entry)
        except asyncio.QueueFull:
            # Yavas istemci: en eski kaydi dusur, yenisini koy.
            try:
                queue.get_nowait()
                queue.put_nowait(entry)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    def history(self, limit: int = 200) -> List[Dict[str, Any]]:
        items = list(self._buffer)
        return items[-limit:] if limit > 0 else items

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


broadcaster = LogBroadcaster()


def setup_logger() -> logging.Logger:
    """Konsol + yayin handler'lariyla logger'i kurar."""
    log = logging.getLogger("VoiceGuard")
    log.setLevel(logging.INFO)
    log.propagate = False

    if log.handlers:
        return log

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    log.addHandler(console_handler)

    broadcaster.setLevel(logging.INFO)
    log.addHandler(broadcaster)

    return log


logger = setup_logger()
