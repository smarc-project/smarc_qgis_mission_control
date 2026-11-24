from dataclasses import dataclass, field
from typing import Annotated, Any
from uuid import UUID, uuid4

from .schema import Column, SchemaMixin, Unit
from .tasks import Task, TaskRegistry

__all__ = ["MissionPlan", "TaskGroup"]


@dataclass
class TaskGroup:
    """A seq or conc node. Children are tasks or more groups."""

    kind: str
    description: str
    uuid: UUID = field(default_factory=uuid4)
    children: list = field(default_factory=list)
    stop_on_first: bool = False

    @property
    def type(self) -> str:
        return self.kind


def node_from_json(data: dict[str, Any]) -> Task | TaskGroup:
    name = data.get("name")
    if name in ("seq", "conc"):
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        raw_uuid = data.get("task-uuid")
        return TaskGroup(
            kind=name,
            description=str(data.get("description") or name),
            uuid=UUID(raw_uuid) if raw_uuid else uuid4(),
            children=[node_from_json(child) for child in data.get("children") or []],
            stop_on_first=params.get("stop-on-first") is True,
        )
    return TaskRegistry.taskFromJson(data)


def node_to_json(node: Task | TaskGroup) -> dict[str, Any]:
    if isinstance(node, TaskGroup):
        params: dict[str, Any] = {}
        if node.kind == "conc" and node.stop_on_first:
            params["stop-on-first"] = True
        return {
            "name": node.kind,
            "description": node.description,
            "task-uuid": str(node.uuid),
            "params": params,
            "children": [node_to_json(child) for child in node.children],
        }
    return node.toJson()


def find_group(plan: "MissionPlan", group_uuid: UUID) -> TaskGroup | None:
    def walk(nodes: list) -> TaskGroup | None:
        for node in nodes:
            if isinstance(node, TaskGroup):
                if node.uuid == group_uuid:
                    return node
                found = walk(node.children)
                if found is not None:
                    return found
        return None
    return walk(plan.tasks)


def iter_leaves(nodes: list) -> list[Task]:
    found: list[Task] = []
    for node in nodes:
        if isinstance(node, TaskGroup):
            found.extend(iter_leaves(node.children))
        else:
            found.append(node)
    return found


@dataclass
class MissionPlan(SchemaMixin):
    # fmt: off
    name        : str
    description : Annotated[str, Column('Description')]
    uuid        : UUID = field(default_factory=uuid4)
    timeout     : Annotated[float, Column('Timeout'), Unit('s')] = 300.0
    tasks       : list = field(default_factory=list)
    # fmt: on

    def leaves(self) -> list[Task]:
        return iter_leaves(self.tasks)

    @classmethod
    def fromJson(cls, data: dict[str, Any]) -> 'MissionPlan':
        tasks = [node_from_json(child) for child in data.get("children") or []]

        return cls(
            # fmt: off
            name        = str(data["name"]),
            description = str(data["description"]),
            uuid        = UUID(data["tst-uuid"]),
            timeout     = float(data["params"].get("timeout", 0)),
            tasks       = tasks,
            # fmt: on
        )

    def toJson(self) -> dict[str, Any]:
        # The officer accepts a start-tst only when the root is seq or conc.
        name = self.name if self.name in ("seq", "conc") else "seq"
        return {
            # fmt: off
            "name"          : name,
            "description"   : self.description,
            "tst-uuid"      : str(self.uuid),
            "params"        : {
                "timeout"       : self.timeout,
            },
            "common-params" : {},
            "children"      : [node_to_json(node) for node in self.tasks]
            # fmt: on
        }
