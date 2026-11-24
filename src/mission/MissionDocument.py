import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from qgis.core import QgsPointXY

from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..domain.missionplan import MissionPlan
from ..domain.missionplan import TaskGroup, find_group, iter_leaves
from ..domain.tasks import (
    PendingWaypointTask,
    Task,
    TaskRegistry,
    UnsupportedTaskCreationError,
)
from ..domain.taskspatial import (
    iterTaskWaypoints,
    locateTaskWaypoint,
    waypointListFields,
    waypointListType,
    waypointType,
)
from ..domain.waypoints import Waypoint
from .MissionIndex import MissionIndex
from .MissionLayerBridge import MissionLayerBridge
from .MissionUndoCommand import (
    AddTaskUndoCommand,
    AddWaypointUndoCommand,
    DeleteTaskUndoCommand,
    DeleteWaypointUndoCommand,
    MissionUndoCommand,
    SetMissionFieldUndoCommand,
    SetTaskDescriptionUndoCommand,
    SetTaskFieldUndoCommand,
    SetWaypointFieldUndoCommand,
    SetWaypointPositionUndoCommand,
)


class MissionDocument(QObject):
    # TODO: move these three signals to MissionContext
    editModeChanged = pyqtSignal(bool)
    editingStarted = pyqtSignal()
    editingFinished = pyqtSignal()

    # TODO: not very precise
    missionChanged = pyqtSignal()

    beforeTaskAdded = pyqtSignal(UUID, int)
    taskAdded = pyqtSignal(UUID, int)
    beforeTaskDeleted = pyqtSignal(UUID)
    taskDeleted = pyqtSignal(UUID, int)
    # TODO: not very precise
    taskChanged = pyqtSignal(UUID)

    beforeWaypointAdded = pyqtSignal(UUID, str, UUID, int)
    waypointAdded = pyqtSignal(UUID, str, UUID)
    beforeWaypointDeleted = pyqtSignal(UUID, str, UUID, int)
    waypointDeleted = pyqtSignal(UUID, str, UUID, int)
    # TODO: not very precise
    waypointChanged = pyqtSignal(UUID)

    plan: MissionPlan
    path: Path
    index: MissionIndex
    layerBridge: MissionLayerBridge
    _keepalive_undo: list[MissionUndoCommand]

    def __init__(self, plan: MissionPlan, path: str | Path,
                 parent: QObject | None = None):
        super().__init__(parent)

        self.plan = plan
        self.path = Path(path)
        self.index = MissionIndex.fromMissionPlan(plan)
        self.layerBridge = MissionLayerBridge(plan, self)
        self._keepalive_undo = []

    @classmethod
    def fromFile(cls, path: str | Path,
                 parent: QObject | None = None) -> 'MissionDocument':
        p = Path(path)
        with p.open() as fp:
            plan = MissionPlan.fromJson(json.load(fp))
        return cls(plan, p, parent)

    def isModified(self) -> bool:
        return (self.layerBridge.waypointLayer.isEditable()
                and self.layerBridge.waypointLayer.isModified())

    def startEditing(self):
        self.layerBridge.waypointLayer.startEditing()

        self.editingStarted.emit()
        self.editModeChanged.emit(True)

    def stopEditing(self, commit: bool):
        if commit:
            self.layerBridge.waypointLayer.commitChanges()
        else:
            self.layerBridge.waypointLayer.rollBack()

        # Drop keepalive command references
        self._keepalive_undo = []

        self.editingFinished.emit()
        self.editModeChanged.emit(False)

    def setMissionField(self, fieldId: int, value: Any):
        oldValue = self.plan.schema().fields[fieldId].value(self.plan)
        if str(value) == str(oldValue):
            # TODO: string comparison is suboptimal
            # No change has occurred
            return

        cmd = SetMissionFieldUndoCommand(self, fieldId, value, oldValue)
        with self.layerBridge.customEditCommand("Modify mission"):
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _setMissionField(self, fieldId: int, value: Any):
        self.plan.schema().fields[fieldId].setValue(self.plan, value)
        self.missionChanged.emit()

    # TODO: accept index in addTask?
    def addGroup(self, kind: str, description: str, parent: TaskGroup | None = None) -> TaskGroup:
        group = TaskGroup(kind=kind, description=description)
        container = self.plan.tasks if parent is None else parent.children
        container.append(group)
        self.taskAdded.emit(group.uuid, len(container) - 1)
        return group

    def deleteGroup(self, group: TaskGroup) -> None:
        if not _remove_group(self.plan.tasks, group):
            return
        for leaf in iter_leaves(group.children):
            self.index.forgetTask(leaf.uuid)
        self.taskAdded.emit(group.uuid, 0)

    def addTask(self, taskType: str, description: str,
                taskUuid: UUID | None = None,
                parent: TaskGroup | None = None) -> None:
        taskCls = TaskRegistry.lookup(taskType)
        requiredFields = taskCls.requiredFields()

        if not requiredFields:
            # Task can be added directly
            task = taskCls(description=description, uuid=taskUuid or uuid4())
            self.addTaskInstance(task, parent)
            return

        if len(requiredFields) == 1:
            field = requiredFields[0]
            waypointCls = waypointType(field.baseType)
            if waypointCls is not None:
                # Task has a single required parameter, which is a waypoint
                pending = PendingWaypointTask(
                    taskCls = taskCls,
                    fieldName = field.name,
                    waypointCls = waypointCls,
                    description = description,
                    taskUuid = taskUuid or uuid4(),
                    waypointUuid = uuid4(),
                )
                # TODO: get mapManager from parent
                self.parent().mapManager.pickInitialWaypoint(pending)
                return

        # Task has multiple required parameters, or a single required parameter, which
        # is not a waypoint
        names = ", ".join(field.name for field in requiredFields)
        raise UnsupportedTaskCreationError(
            f"Creating task '{taskType}' requires unsupported fields: {names}")

    def addPendingWaypointTask(self, pendingTask: PendingWaypointTask,
                               point: QgsPointXY) -> None:
        waypoint = pendingTask.waypointCls(
            latitude = point.y(),
            longitude = point.x(),
            uuid = pendingTask.waypointUuid
        )
        task = pendingTask.taskCls(
            description = pendingTask.description,
            uuid = pendingTask.taskUuid,
            **{pendingTask.fieldName: waypoint}
        )
        self.addTaskInstance(task)

    def addTaskInstance(self, task: Task, parent: TaskGroup | None = None) -> None:
        cmd = AddTaskUndoCommand(self, task, parent)

        text = f"Add task {task.type} ({task.description})"
        with self.layerBridge.customEditCommand(text):
            for waypoint in iterTaskWaypoints(task):
                feat = self.layerBridge._waypointToFeature(task.uuid, task.description, waypoint)
                self.layerBridge.waypointLayer.addFeature(feat)
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _container(self, parent_uuid: UUID | None) -> list:
        if parent_uuid is None:
            return self.plan.tasks
        group = find_group(self.plan, parent_uuid)
        return self.plan.tasks if group is None else group.children

    def _addTaskAt(self, task: Task, index: int, parent_uuid: UUID | None = None):
        self.beforeTaskAdded.emit(task.uuid, index)

        self._container(parent_uuid).insert(index, task)
        self.index.registerTask(task)

        self.taskAdded.emit(task.uuid, index)

    def deleteTaskAt(self, index: int) -> None:
        try:
            task = self.plan.tasks[index]
        except IndexError:
            return
        if isinstance(task, Task):
            self.deleteTask(task)

    def deleteTask(self, task: Task) -> None:
        parent = _owner_group(self.plan.tasks, task)
        if parent is False:
            return
        container = self.plan.tasks if parent is None else parent.children
        try:
            index = container.index(task)
        except ValueError:
            return
        cmd = DeleteTaskUndoCommand(self, task, parent)

        text = f"Delete task {task.type} ({task.description})"
        with self.layerBridge.customEditCommand(text):
            for waypoint in iterTaskWaypoints(task):
                fid = self.layerBridge.featureIdForWaypointUuid(waypoint.uuid)
                if fid is not None:
                    self.layerBridge.waypointLayer.deleteFeature(fid)
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _deleteTaskAt(self, index: int, parent_uuid: UUID | None = None):
        task = self._container(parent_uuid).pop(index)

        self.beforeTaskDeleted.emit(task.uuid)
        self.index.forgetTask(task.uuid)

        self.taskDeleted.emit(task.uuid, index)

    # TODO: move task to a specific index
    # def moveTask(self, taskUuid: UUID, index: int): ...

    # TODO: accept index?
    # TODO: other waypoint parameters
    def addWaypoint(self, taskUuid: UUID, description: str, latitude: float, longitude: float,
                    waypointUuid: UUID | None = None,
                    fieldName: str | None = None) -> None:
        task = self.index.taskByUuid(taskUuid)
        if task is None:
            # TODO: invalid mapping
            return

        fields = waypointListFields(type(task))
        if fieldName is None:
            if len(fields) != 1:
                raise ValueError("fieldName is required for this task")
            field = fields[0]
        else:
            try:
                field = [field for field in fields if field.name == fieldName][0]
            except IndexError:
                raise ValueError(f"Task has no waypoint list named '{fieldName}'") \
                    from None

        waypointCls = waypointListType(field.baseType)
        assert(waypointCls is not None)
        waypoint = waypointCls(
            latitude = latitude,
            longitude = longitude,
            uuid = waypointUuid or uuid4()
        )

        feat = self.layerBridge._waypointToFeature(taskUuid, description, waypoint)
        cmd = AddWaypointUndoCommand(self, task, field.name, waypoint)

        with self.layerBridge.customEditCommand("Add waypoint"):
            self.layerBridge.waypointLayer.addFeature(feat)
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

        # task.waypoints.append(waypoint)
        # self.index.registerWaypoint(taskUuid, waypoint)

    def _addTaskWaypointAt(self, task: Task, fieldName: str,
                           waypoint: Waypoint, index: int) -> None:
        waypoints = getattr(task, fieldName)
        self.beforeWaypointAdded.emit(
            task.uuid, fieldName, waypoint.uuid, index)
        waypoints.insert(index, waypoint)
        self.index.registerWaypoint(task.uuid, waypoint)
        self.waypointAdded.emit(task.uuid, fieldName, waypoint.uuid)

    def deleteWaypoint(self, waypointUuid: UUID):
        task = self.index.taskByWaypointUuid(waypointUuid)
        if task is None:
            # TODO: invalid mapping
            return

        location = locateTaskWaypoint(task, waypointUuid)
        if location is None:
            # TODO: invalid mapping
            return
        fieldName, index, waypoint = location

        if index is None:
            # TODO: A single waypoint field cannot be removed independently of its task
            self.deleteTaskAt(self.plan.tasks.index(task))
            return

        fid = self.layerBridge.featureIdForWaypointUuid(waypointUuid)
        assert(fid is not None)

        cmd = DeleteWaypointUndoCommand(self, task, fieldName, waypoint)

        with self.layerBridge.customEditCommand("Delete waypoint"):
            self.layerBridge.waypointLayer.deleteFeature(fid)
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def deleteWaypoints(self, waypointUuids: list[UUID]):
        if len(waypointUuids) == 1:
            self.deleteWaypoint(waypointUuids[0])
            return

        with self.layerBridge.customEditCommand("Delete waypoints"):
            for waypointUuid in waypointUuids:
                self.deleteWaypoint(waypointUuid)

    def _deleteTaskWaypointAt(self, task: Task, fieldName: str,
                              index: int) -> None:
        waypoints = getattr(task, fieldName)
        waypoint = waypoints[index]
        self.beforeWaypointDeleted.emit(
            task.uuid, fieldName, waypoint.uuid, index)
        waypoints.pop(index)
        self.index.forgetWaypoint(waypoint.uuid)
        self.waypointDeleted.emit(task.uuid, fieldName, waypoint.uuid, index)

    def setWaypointPosition(self, waypointUuid: UUID, latitude: float,
                            longitude: float):
        waypoint = self.index.waypointByUuid(waypointUuid)
        if waypoint is None:
            # TODO: invalid mapping
            return

        cmd = SetWaypointPositionUndoCommand(self, waypoint, latitude, longitude)
        with self.layerBridge.customEditCommand("Move waypoint"):
            self.layerBridge.moveWaypointFeature(waypointUuid, latitude, longitude)
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _setWaypointPosition(self, waypoint: Waypoint, latitude: float,
                             longitude: float):
        waypoint.latitude = latitude
        waypoint.longitude = longitude
        self.waypointChanged.emit(waypoint.uuid)

    def setWaypointField(self, waypointUuid: UUID, fieldId: int, value: Any):
        waypoint = self.index.waypointByUuid(waypointUuid)
        if waypoint is None:
            # TODO: invalid mapping
            return

        # TODO: Location should be changed via setWaypointPosition
        assert(fieldId > 1)

        spec = waypoint.schema().fields[fieldId]
        oldValue = waypoint.schema().fields[fieldId].value(waypoint)
        cmd = SetWaypointFieldUndoCommand(self, waypoint, fieldId, value, oldValue)
        with self.layerBridge.customEditCommand("Modify waypoint"):
            if spec.name == 'tolerance':
                self.layerBridge.setWaypointAttribute(waypointUuid, 'tolerance', value)
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _setWaypointField(self, waypoint: Waypoint, fieldId: int, value: Any):
        waypoint.schema().fields[fieldId].setValue(waypoint, value)
        self.waypointChanged.emit(waypoint.uuid)

    def setTaskField(self, taskUuid: UUID, fieldId: int, value: Any) -> None:
        task = self.index.taskByUuid(taskUuid)
        if task is None:
            # TODO: invalid mapping
            return

        oldValue = task.schema().fields[fieldId].value(task)
        cmd = SetTaskFieldUndoCommand(self, task, fieldId, value, oldValue)
        with self.layerBridge.customEditCommand("Modify task"):
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _setTaskField(self, task: Task, fieldId: int, value: Any) -> None:
        task.schema().fields[fieldId].setValue(task, value)
        self.taskChanged.emit(task.uuid)

    def setTaskDescription(self, taskUuid: UUID, value: str) -> None:
        task = self.index.taskByUuid(taskUuid)
        if task is None:
            # TODO: invalid mapping
            return

        oldValue = task.description
        cmd = SetTaskDescriptionUndoCommand(self, task, value, oldValue)
        with self.layerBridge.customEditCommand("Modify task description"):
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _setTaskDescription(self, task: Task, value: str) -> None:
        task.description = value
        self.layerBridge.updateTaskDescriptionLabel(task.uuid, value)
        self.taskChanged.emit(task.uuid)


def _owner_group(nodes: list, target, owner: TaskGroup | None = None):
    if target in nodes:
        return owner
    for node in nodes:
        if isinstance(node, TaskGroup):
            found = _owner_group(node.children, target, node)
            if found is not False:
                return found
    return False


def _remove_group(nodes: list, group: TaskGroup) -> bool:
    if group in nodes:
        nodes.remove(group)
        return True
    for node in nodes:
        if isinstance(node, TaskGroup) and _remove_group(node.children, group):
            return True
    return False
