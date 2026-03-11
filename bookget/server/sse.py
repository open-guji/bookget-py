"""SSE (Server-Sent Events) event bus and response helper."""
import asyncio
import json
from typing import Callable


class EventBus:
    """
    Simple pub/sub bus for SSE events.
    Subscribers receive events via asyncio.Queue.
    """

    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        try:
            self._queues.remove(q)
        except ValueError:
            pass

    def publish(self, event_type: str, data: dict):
        """Push an event to all subscribers."""
        msg = {"type": event_type, **data}
        for q in list(self._queues):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass  # Drop event if queue is full

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)


def make_sse_data(event_type: str, data: dict) -> str:
    """Format a dict as an SSE message string."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {payload}\n\n"


async def sse_stream(
    request,
    bus: EventBus,
    filter_task_id: str | None = None,
):
    """
    aiohttp response handler that streams SSE events from an EventBus.

    Args:
        request: aiohttp Request
        bus: EventBus to subscribe to
        filter_task_id: if set, only emit events for this task
    """
    from aiohttp import web

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
    await response.prepare(request)

    # Send initial ping
    await response.write(b": ping\n\n")

    q = bus.subscribe()
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                if filter_task_id and event.get("taskId") != filter_task_id:
                    continue
                event_type = event.pop("type", "message")
                msg = make_sse_data(event_type, event)
                await response.write(msg.encode("utf-8"))
            except asyncio.TimeoutError:
                # Keepalive ping
                await response.write(b": ping\n\n")
            except (ConnectionResetError, asyncio.CancelledError):
                break
    finally:
        bus.unsubscribe(q)

    return response
