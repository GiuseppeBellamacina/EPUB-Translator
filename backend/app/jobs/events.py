"""Job messages: published once, followed by any number of clients (observer pattern).

Each message is kept in a short per-book log (a page reload shows the latest
activity) and pushed to the queues of the WebSocket clients following that book.
"""

import asyncio
import time
from collections import deque

from app.agents.pipeline import TranslationProgress

FINAL = None  # sent to subscribers when the book's job is over
RECENT = 200  # messages kept per book

# Bulky payloads persisted server-side but not sent to the client
_SERVER_ONLY_KEYS = {"translated_html", "translations"}


def client_message(event: TranslationProgress) -> dict:
    return {
        "event": event.event_type,
        "chapter_index": event.chapter_index,
        "total_chapters": event.total_chapters,
        "chunk_index": event.chunk_index,
        "total_chunks": event.total_chunks,
        "message": event.message,
        "data": {k: v for k, v in event.data.items() if k not in _SERVER_ONLY_KEYS},
    }


class EventBus:
    def __init__(self):
        self.recent: dict[int, deque] = {}
        self._subscribers: dict[int, set[asyncio.Queue]] = {}

    def reset_log(self, book_id: int) -> None:
        """A new run of the book: its log starts empty."""
        self.recent[book_id] = deque(maxlen=RECENT)

    def publish(self, book_id: int, message: dict | None) -> None:
        if message is not None:
            message = {**message, "ts": time.time()}
            self.recent.setdefault(book_id, deque(maxlen=RECENT)).append(message)
        for queue in self._subscribers.get(book_id, ()):
            queue.put_nowait(message)

    def subscribe(self, book_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(book_id, set()).add(queue)
        return queue

    def unsubscribe(self, book_id: int, queue: asyncio.Queue) -> None:
        self._subscribers.get(book_id, set()).discard(queue)

    def log(self, book_id: int) -> list[dict]:
        """The book's recent messages, newest first."""
        return list(reversed(self.recent.get(book_id, [])))
