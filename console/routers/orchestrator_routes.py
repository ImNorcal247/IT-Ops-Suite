import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from console.deps import get_sink_config, require_user_api
from modules.ticket_orchestrator import create_ticket

router = APIRouter(prefix="/api", tags=["orchestrator"])


class SubmitBody(BaseModel):
    raw_input: str


@router.post("/orchestrator/submit")
async def submit(body: SubmitBody, user=Depends(require_user_api), sink_config=Depends(get_sink_config)):
    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def progress_callback(stage_name, result):
            loop.call_soon_threadsafe(queue.put_nowait, {"stage": stage_name, "result": result})

        async def run():
            try:
                final = await asyncio.to_thread(create_ticket, body.raw_input, progress_callback, sink_config)
                await queue.put({"stage": "final", "result": final})
            except Exception as e:
                await queue.put({"stage": "error", "result": {"error": str(e)}})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            await task

    return StreamingResponse(event_stream(), media_type="text/event-stream")
