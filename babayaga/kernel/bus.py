"""An asynchronous publish/subscribe event bus — the OS "message kernel".

Agents and adapters never call each other directly; they publish typed messages
to a :class:`Topic` and subscribe to the topics they care about. This keeps the
system loosely coupled and makes it trivial to add new agents, tap the stream
for logging, or replay history.

Handlers may be plain functions or coroutines; both are awaited uniformly.
Exceptions raised by one subscriber are isolated so a single misbehaving agent
cannot take down the bus.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

from babayaga.kernel.events import Topic

log = logging.getLogger("babayaga.bus")

Handler = Callable[[Any], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[Topic, list[Handler]] = defaultdict(list)
        self._published = 0

    def subscribe(self, topic: Topic, handler: Handler) -> None:
        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: Topic, handler: Handler) -> None:
        if handler in self._subscribers[topic]:
            self._subscribers[topic].remove(handler)

    @property
    def published_count(self) -> int:
        return self._published

    async def publish(self, topic: Topic, message: Any) -> None:
        """Deliver ``message`` to every subscriber of ``topic``.

        Handlers run sequentially in subscription order so that, for example, the
        risk agent always sees a signal before the execution agent acts on the
        resulting decision. Async handlers are awaited; sync handlers run inline.
        """
        self._published += 1
        for handler in list(self._subscribers.get(topic, ())):
            try:
                result = handler(message)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 — isolate a faulty subscriber
                log.exception("subscriber %r failed handling %s", handler, topic)

    def publish_soon(self, topic: Topic, message: Any) -> "asyncio.Task[None]":
        """Fire-and-forget publish, for use from inside a running loop."""
        return asyncio.ensure_future(self.publish(topic, message))
