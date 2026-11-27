from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from .missionplan import MissionPlan
from .schema import Column, SchemaMixin
from .tasks import CustomTask, Task


@dataclass
class WaraPsAvailableTask:
    name: str
    signals: list[str]

@dataclass
class WaraPsExecutingTask(SchemaMixin):
    description: Annotated[str, Column('Description')]
    type: Annotated[str, Column('Type')]
    status: Annotated[str, Column('Status')]

    uuid: UUID


def actionServerName(task: Task) -> str:
    """The name the officer looks a task's action server up by.

    A custom-task runs the action named in its params; the officer resolves that
    name before it checks whether the server is busy.
    """
    if isinstance(task, CustomTask):
        return task.action_name
    return task.type


def tasksBlockingPlan(
    plan: MissionPlan,
    executing: list[WaraPsExecutingTask],
) -> list[WaraPsExecutingTask]:
    """The executing tasks whose action server the plan also needs.

    The officer refuses a start-tst while any of these runs
    ("task already executing on ...").
    """
    needed = {actionServerName(task) for task in plan.leaves()}
    return [task for task in executing if task.type in needed]
