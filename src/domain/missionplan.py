from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any
from uuid import UUID, uuid4

from .schema import Column, SchemaMixin, Unit
from .tasks import Task, TaskRegistry

__all__ = ["GroupKind", "MissionNode", "MissionPlan", "TaskGroup"]


class GroupKind(str, Enum):
    """The two composite TST nodes the officer runs. The value is the JSON name."""

    SEQ = "seq"
    CONC = "conc"

    @property
    def label(self) -> str:
        return "Sequence" if self is GroupKind.SEQ else "Concurrent"


@dataclass
class TaskGroup:
    """A seq or conc node. Children are tasks or more groups."""

    kind: GroupKind
    description: str
    uuid: UUID = field(default_factory=uuid4)
    children: list["MissionNode"] = field(default_factory=list)
    stop_on_first: bool = False

    @property
    def type(self) -> str:
        return self.kind.value


# One node of the mission tree: a task leaf or a group of more nodes.
MissionNode = Task | TaskGroup


def node_from_json(data: dict[str, Any]) -> MissionNode:
    name = data.get("name")
    if name in GroupKind._value2member_map_:
        kind = GroupKind(name)
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        raw_uuid = data.get("task-uuid")
        return TaskGroup(
            kind=kind,
            description=str(data.get("description") or kind.label),
            uuid=UUID(raw_uuid) if raw_uuid else uuid4(),
            children=[node_from_json(child) for child in data.get("children") or []],
            stop_on_first=params.get("stop-on-first") is True,
        )
    return TaskRegistry.taskFromJson(data)


def node_to_json(node: MissionNode) -> dict[str, Any]:
    if isinstance(node, TaskGroup):
        params: dict[str, Any] = {}
        if node.kind is GroupKind.CONC and node.stop_on_first:
            params["stop-on-first"] = True
        return {
            "name": node.kind.value,
            "description": node.description,
            "task-uuid": str(node.uuid),
            "params": params,
            "children": [node_to_json(child) for child in node.children],
        }
    return node.toJson()


def walk(nodes: list[MissionNode],
         owner: TaskGroup | None = None) -> Iterator[tuple[TaskGroup | None, int, MissionNode]]:
    """Every node under nodes, depth first, as (owning group or None, row, node)."""
    for row, node in enumerate(nodes):
        yield owner, row, node
        if isinstance(node, TaskGroup):
            yield from walk(node.children, node)


def leaves(nodes: list[MissionNode]) -> list[Task]:
    return [node for _, _, node in walk(nodes) if not isinstance(node, TaskGroup)]


@dataclass
class MissionPlan(SchemaMixin):
    # fmt: off
    name        : str
    description : Annotated[str, Column('Description')]
    uuid        : UUID = field(default_factory=uuid4)
    timeout     : Annotated[float, Column('Timeout'), Unit('s')] = 300.0
    tasks       : list[MissionNode] = field(default_factory=list)
    # fmt: on

    @property
    def root_kind(self) -> GroupKind:
        # The officer accepts a start-tst only when the root is seq or conc.
        if self.name in GroupKind._value2member_map_:
            return GroupKind(self.name)
        return GroupKind.SEQ

    def children_of(self, group: TaskGroup | None) -> list[MissionNode]:
        return self.tasks if group is None else group.children

    def leaves(self) -> list[Task]:
        return leaves(self.tasks)

    def emptyGroups(self) -> list[TaskGroup]:
        """Groups with no children, at any depth. The officer refuses a TST that has one."""
        return [node for _, _, node in walk(self.tasks) if isinstance(node, TaskGroup) and not node.children]

    def findNode(self, uuid: UUID) -> MissionNode | None:
        for _, _, node in walk(self.tasks):
            if node.uuid == uuid:
                return node
        return None

    def findGroup(self, groupUuid: UUID | None) -> TaskGroup | None:
        # None stands for the plan's root, which is not a group.
        node = None if groupUuid is None else self.findNode(groupUuid)
        return node if isinstance(node, TaskGroup) else None

    def locate(self, target: MissionNode) -> tuple[TaskGroup | None, int] | None:
        """Return (owning group or None for the root, row), or None if target is not in the plan."""
        for owner, row, node in walk(self.tasks):
            if node is target:
                return owner, row
        return None

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
        return {
            # fmt: off
            "name"          : self.root_kind.value,
            "description"   : self.description,
            "tst-uuid"      : str(self.uuid),
            "params"        : {
                "timeout"       : self.timeout,
            },
            "common-params" : {},
            "children"      : [node_to_json(node) for node in self.tasks]
            # fmt: on
        }
