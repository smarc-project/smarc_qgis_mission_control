from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qgis.PyQt.QtWidgets import QUndoCommand

from ..domain.tasks import Task
from ..domain.waypoints import Waypoint

if TYPE_CHECKING:
    # Prevent circular dependencies
    from .MissionDocument import MissionDocument

__all__ = [
    "MissionUndoCommand",
    "AddTaskUndoCommand",
    "DeleteTaskUndoCommand",
    "AddWaypointUndoCommand",
    "DeleteWaypointUndoCommand",
    "SetWaypointPositionUndoCommand",
    "SetWaypointFieldUndoCommand",
    "SetTaskFieldUndoCommand",
    "SetTaskDescriptionUndoCommand",
    "SetMissionFieldUndoCommand",
]

class MissionUndoCommand(QUndoCommand):
    _doc: MissionDocument

    def __init__(self, doc: MissionDocument) -> None:
        super().__init__()

        self._doc = doc

class AddTaskUndoCommand(MissionUndoCommand):
    _task: Task

    def __init__(self, doc: MissionDocument, task: Task) -> None:
        super().__init__(doc)

        self._task = task
        self._index = len(self._doc.plan.tasks)

    def redo(self) -> None:
        print(self.__class__.__name__, 'redo')
        self._doc._addTaskAt(self._task, self._index)

    def undo(self) -> None:
        print(self.__class__.__name__, 'undo')
        self._doc._deleteTaskAt(self._index)

class DeleteTaskUndoCommand(MissionUndoCommand):
    _task: Task

    def __init__(self, doc: MissionDocument, task: Task) -> None:
        super().__init__(doc)

        self._task = task
        self._index = self._doc.plan.tasks.index(self._task)

    def redo(self) -> None:
        print(self.__class__.__name__, 'redo')
        self._doc._deleteTaskAt(self._index)

    def undo(self) -> None:
        print(self.__class__.__name__, 'undo')
        self._doc._addTaskAt(self._task, self._index)

class AddWaypointUndoCommand(MissionUndoCommand):
    _task: Task
    _waypoint: Waypoint

    def __init__(self, doc: MissionDocument, task: Task, fieldName: str,
                 waypoint: Waypoint) -> None:
        super().__init__(doc)

        self._task = task
        self._fieldName = fieldName
        self._waypoint = waypoint
        self._index = len(getattr(self._task, self._fieldName))

    def redo(self) -> None:
        print(self.__class__.__name__, 'redo')
        self._doc._addTaskWaypointAt(self._task, self._fieldName, self._waypoint,
                                     self._index)

    def undo(self) -> None:
        print(self.__class__.__name__, 'undo')
        self._doc._deleteTaskWaypointAt(self._task, self._fieldName, self._index)

class DeleteWaypointUndoCommand(MissionUndoCommand):
    _task: Task
    _waypoint: Waypoint

    def __init__(self, doc: MissionDocument, task: Task, fieldName: str,
                 waypoint: Waypoint) -> None:
        super().__init__(doc)

        self._task = task
        self._fieldName = fieldName
        self._waypoint = waypoint
        self._index = getattr(self._task, self._fieldName).index(self._waypoint)

    def redo(self) -> None:
        print(self.__class__.__name__, 'redo')
        self._doc._deleteTaskWaypointAt(self._task, self._fieldName, self._index)

    def undo(self) -> None:
        print(self.__class__.__name__, 'undo')
        self._doc._addTaskWaypointAt(self._task, self._fieldName, self._waypoint,
                                     self._index)

class SetWaypointPositionUndoCommand(MissionUndoCommand):
    _waypoint: Waypoint
    _newPos: tuple[float, float]
    _oldPos: tuple[float, float]

    def __init__(self, doc: MissionDocument, waypoint: Waypoint, latitude: float,
                 longitude: float):
        super().__init__(doc)

        self._waypoint = waypoint
        self._newPos = (latitude, longitude)
        self._oldPos = (waypoint.latitude, waypoint.longitude)

    def redo(self):
        print(self.__class__.__name__, 'redo')
        self._doc._setWaypointPosition(self._waypoint, *self._newPos)

    def undo(self):
        print(self.__class__.__name__, 'undo')
        self._doc._setWaypointPosition(self._waypoint, *self._oldPos)

class SetWaypointFieldUndoCommand(MissionUndoCommand):
    _waypoint: Waypoint
    _value: Any
    _oldValue: Any

    def __init__(self, doc: MissionDocument, waypoint: Waypoint, fieldId: int,
                 value: Any, oldValue: Any):
        super().__init__(doc)

        self._waypoint = waypoint
        self._fieldId = fieldId
        self._value = value
        self._oldValue = oldValue

    def redo(self):
        print(self.__class__.__name__, 'redo')
        self._doc._setWaypointField(self._waypoint, self._fieldId, self._value)

    def undo(self):
        print(self.__class__.__name__, 'undo')
        self._doc._setWaypointField(self._waypoint, self._fieldId, self._oldValue)

class SetTaskFieldUndoCommand(MissionUndoCommand):
    _task: Task
    _fieldId: int
    _value: Any
    _oldValue: Any

    def __init__(self, doc: MissionDocument, task: Task, fieldId: int, value: Any,
                 oldValue: Any):
        super().__init__(doc)

        self._task = task
        self._fieldId = fieldId
        self._value = value
        self._oldValue = oldValue

    def redo(self):
        print(self.__class__.__name__, 'redo')
        self._doc._setTaskField(self._task, self._fieldId, self._value)

    def undo(self):
        print(self.__class__.__name__, 'undo')
        self._doc._setTaskField(self._task, self._fieldId, self._oldValue)

class SetTaskDescriptionUndoCommand(MissionUndoCommand):
    _task: Task
    _value: str
    _oldValue: str

    def __init__(self, doc: MissionDocument, task: Task, value: str, oldValue: str):
        super().__init__(doc)

        self._task = task
        self._value = value
        self._oldValue = oldValue

    def redo(self):
        print(self.__class__.__name__, 'redo')
        self._doc._setTaskDescription(self._task, self._value)

    def undo(self):
        print(self.__class__.__name__, 'undo')
        self._doc._setTaskDescription(self._task, self._oldValue)

class SetMissionFieldUndoCommand(MissionUndoCommand):
    _value: Any
    _oldValue: Any

    def __init__(self, doc: MissionDocument, fieldId: int, value: Any, oldValue: Any):
        super().__init__(doc)

        self._fieldId = fieldId
        self._value = value
        self._oldValue = oldValue

    def redo(self):
        print(self.__class__.__name__, 'redo')
        self._doc._setMissionField(self._fieldId, self._value)

    def undo(self):
        print(self.__class__.__name__, 'undo')
        self._doc._setMissionField(self._fieldId, self._oldValue)
