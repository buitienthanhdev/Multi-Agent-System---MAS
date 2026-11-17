"""Temporal integration: Mission lifecycle workflow. Workflow code is deterministic; all DB/LLM/network work
happens in activities, which call the same engine used by the local worker.

Retry ownership: Temporal retries the *activity* (task step). External side effects inside it go through the
Action Gateway, which is idempotent and reconciles before re-sending, so Temporal retries never duplicate them."""
from __future__ import annotations

from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from atlas.execution import engine


@activity.defn
def run_ready_tasks(mission_id: str) -> dict:
    worker_id = f"temporal:{activity.info().workflow_id}:{activity.info().attempt}"
    n = engine.run_until_idle(worker_id, mission_id)
    return {"ran": n, "terminal": engine.mission_terminal(mission_id)}


@workflow.defn
class MissionWorkflow:
    def __init__(self) -> None:
        self._nudged = False
        self._stop = False

    @workflow.signal
    def nudge(self) -> None:  # approval, resume, new input
        self._nudged = True

    @workflow.signal
    def stop(self) -> None:
        self._stop = True

    @workflow.run
    async def run(self, mission_id: str, poll_seconds: int = 60) -> str:
        while not self._stop:
            self._nudged = False
            res = await workflow.execute_activity(
                run_ready_tasks, mission_id, start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=2)))
            if res["terminal"]:
                return "terminal"
            try:
                await workflow.wait_condition(lambda: self._nudged or self._stop, timeout=timedelta(seconds=poll_seconds))
            except TimeoutError:
                pass
        return "stopped"


async def start_mission_workflow(client, mission_id: str, task_queue: str) -> None:  # noqa: ANN001
    from temporalio.exceptions import WorkflowAlreadyStartedError
    try:
        await client.start_workflow(MissionWorkflow.run, mission_id, id=f"mission-{mission_id}", task_queue=task_queue)
    except WorkflowAlreadyStartedError:
        pass  # idempotent dispatch from outbox
