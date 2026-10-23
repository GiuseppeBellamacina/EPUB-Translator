"""WebSocket endpoint that starts and follows a translation job.

Protocol:
    client → {"action": "start", "provider_id": 1, "source_language": "english",
              "target_language": "italian", "model": "...", "restart": false, ...}
           | {"action": "watch"}                       (follow a running/queued job)
    client → {"action": "stop"}                       (pauses; resumable)
    server → {"event": ..., "chapter_index": ..., "message": ..., "data": {...}, "ts": ...}

The job runs on the server (``app/jobs``): a disconnect only stops
following it. A job resumes from its checkpoints by default; ``restart: true``
starts over. The socket closes once the book's job is over.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.jobs import FINAL, RunConfig, jobs

ws_router = APIRouter()


async def _fail(websocket: WebSocket, message: str) -> None:
    await websocket.send_json({"event": "error", "error": message, "message": message})
    await websocket.close()


@ws_router.websocket("/ws/translate/{book_id}")
async def translate_ws(websocket: WebSocket, book_id: int):
    await websocket.accept()
    try:
        data = await websocket.receive_json()
    except WebSocketDisconnect:
        return

    queue = jobs.events.subscribe(book_id)  # before starting: no message is missed
    try:
        if data.get("action") == "start":
            try:
                config = RunConfig(**{k: v for k, v in data.items() if k != "action"})
                await jobs.enqueue([book_id], config, front=True)
            except (ValidationError, ValueError) as e:
                return await _fail(websocket, str(e))
            if jobs.runner.active and not jobs.is_running(book_id):
                await websocket.send_json(
                    {"event": "queued", "message": "Waiting for the book before it to finish"}
                )
        elif data.get("action") == "watch":
            if not jobs.is_running(book_id) and not await jobs.is_waiting(book_id):
                return await websocket.close()
        else:
            return await _fail(websocket, "Expected 'start' or 'watch' action")

        async def listen_for_stop() -> None:
            try:
                while True:
                    msg = await websocket.receive_json()
                    if msg.get("action") == "stop" and not jobs.scheduler.stop(book_id):
                        await jobs.queue.remove_waiting(book_id)
                        queue.put_nowait({"event": "cancelled", "message": "Removed from queue"})
                        queue.put_nowait(FINAL)
            except Exception:  # disconnect: stop following, the job goes on
                queue.put_nowait(FINAL)

        listener = asyncio.create_task(listen_for_stop())
        try:
            while (message := await queue.get()) is not FINAL:
                await websocket.send_json(message)
        finally:
            listener.cancel()
        await websocket.close()
    except (WebSocketDisconnect, RuntimeError):
        pass  # client gone: the job keeps running
    finally:
        jobs.events.unsubscribe(book_id, queue)


@ws_router.post("/api/translate/{book_id}/stop")
async def stop_translation(book_id: int):
    """Pause a book's running job (and halt the queue), or take it out of the queue."""
    if jobs.scheduler.stop(book_id):
        return {"status": "stopping"}
    if await jobs.queue.remove_waiting(book_id):
        return {"status": "dequeued"}
    return {"status": "no_active_job"}
