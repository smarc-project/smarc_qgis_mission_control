from dataclasses import dataclass, field
from typing import Annotated, Any
from uuid import UUID, uuid4

from .schema import Column, SchemaMixin, Unit
from .tasks import Task, TaskRegistry

__all__ = ["MissionPlan"]


@dataclass
class MissionPlan(SchemaMixin):
    # fmt: off
    name        : str
    description : Annotated[str, Column('Description')]
    uuid        : UUID = field(default_factory=uuid4)
    timeout     : Annotated[float, Column('Timeout'), Unit('s')] = 300.0
    tasks       : list[Task] = field(default_factory=list)
    # fmt: on

    @classmethod
    def fromJson(cls, data: dict[str, Any]) -> 'MissionPlan':
        tasks = []
        for c in data["children"]:
            tasks.append(TaskRegistry.taskFromJson(c))

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
            "name"          : self.name,
            "description"   : self.description,
            "tst-uuid"      : str(self.uuid),
            "params"        : {
                "timeout"       : self.timeout,
            },
            "common-params" : {},
            "children"      : [t.toJson() for t in self.tasks]
            # fmt: on
        }
