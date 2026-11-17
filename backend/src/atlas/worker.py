"""Worker process: outbox dispatch + task execution + report scheduler. Run: `uv run python -m atlas.worker`.

Modes:
- local (default): DB-leased engine loop. Durable via PostgreSQL task state + leases.
- temporal (ATLAS_TEMPORAL_ADDRESS set): runs a Temporal worker; outbox events start/nudge MissionWorkflows."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import time
from datetime import timedelta

from sqlalchemy import select

from atlas.config import get_settings
from atlas.db import SessionLocal, create_all, utcnow
from atlas.execution import engine
from atlas.models import OutboxEvent
from atlas.reporting.reports import run_due_reports

log = logging.getLogger("atlas.worker")


def dispatch_outbox(sender=None) -> int:  # noqa: ANN001
    """Deliver pending outbox events. `sender(event)` raises on failure -> retried with backoff, dead after 10."""
    s = SessionLocal()
    n = 0
    try:
        for ev in s.scalars(select(OutboxEvent).where(OutboxEvent.status == "pending", OutboxEvent.available_at <= utcnow()).limit(50)):
            try:
                if sender:
                    sender(ev)
                ev.status = "done"
                n += 1
            except Exception as e:
                ev.attempts += 1
                ev.last_error = f"{type(e).__name__}: {e}"[:500]
                ev.available_at = utcnow() + timedelta(seconds=min(300, 2 ** ev.attempts))
                if ev.attempts >= 10:
                    ev.status = "dead"
            s.commit()
    finally:
        s.close()
    return n


def local_loop(worker_id: str, once: bool = False, idle_sleep: float = 1.0) -> None:
    while True:
        dispatch_outbox()
        ran = engine.run_until_idle(worker_id, max_tasks=20)
        s = SessionLocal()
        try:
            run_due_reports(s)
            s.commit()
        finally:
            s.close()
        if once:
            return
        if not ran:
            time.sleep(idle_sleep)


async def temporal_main(worker_id: str) -> None:  # pragma: no cover - needs Temporal server
    from concurrent.futures import ThreadPoolExecutor

    from temporalio.client import Client
    from temporalio.worker import Worker

    from atlas.execution.temporal_workflows import MissionWorkflow, run_ready_tasks, start_mission_workflow
    st = get_settings()
    client = await Client.connect(st.temporal_address)
    loop = asyncio.get_running_loop()

    def sender(ev: OutboxEvent) -> None:
        mid = ev.payload["mission_id"]
        if ev.topic == "mission.started":
            asyncio.run_coroutine_threadsafe(start_mission_workflow(client, mid, st.temporal_task_queue), loop).result(30)
        elif ev.topic == "mission.nudge":
            asyncio.run_coroutine_threadsafe(client.get_workflow_handle(f"mission-{mid}").signal("nudge"), loop).result(30)

    async def outbox_pump() -> None:
        while True:
            await asyncio.to_thread(dispatch_outbox, sender)
            s = SessionLocal()
            try:
                run_due_reports(s)
                s.commit()
            finally:
                s.close()
            await asyncio.sleep(1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        w = Worker(client, task_queue=st.temporal_task_queue, workflows=[MissionWorkflow], activities=[run_ready_tasks],
                   activity_executor=pool)
        await asyncio.gather(w.run(), outbox_pump())


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--worker-id", default=f"{socket.gethostname()}-{os.getpid()}")
    a = p.parse_args()
    create_all()
    if get_settings().temporal_address:
        asyncio.run(temporal_main(a.worker_id))
    else:
        local_loop(a.worker_id, once=a.once)


if __name__ == "__main__":
    main()
