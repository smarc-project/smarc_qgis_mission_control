import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from qgis.core import QgsPointXY

from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..domain.missionplan import GroupKind, MissionNode, MissionPlan, TaskGroup, leaves
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
    AddGroupUndoCommand,
    AddTaskUndoCommand,
    AddWaypointUndoCommand,
    DeleteGroupUndoCommand,
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

    # A group's own add and delete. The task signals above carry only tasks.
    groupAdded = pyqtSignal(UUID, int)
    groupDeleted = pyqtSignal(UUID, int)

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

    def addGroup(self, kind: GroupKind, owner: TaskGroup | None = None) -> TaskGroup:
        # owner is the group the new one goes into, None for the plan's root. Here `group`
        # already names the new group, so the task methods' `group` argument is `owner`.
        group = TaskGroup(kind=kind, description=kind.label)
        cmd = AddGroupUndoCommand(self, group, owner)
        with self.layerBridge.customEditCommand(f"Add {kind.label.lower()}"):
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)
        return group

    def deleteGroup(self, group: TaskGroup) -> None:
        location = self.plan.locate(group)
        if location is None:
            return
        cmd = DeleteGroupUndoCommand(self, group, location[0])
        with self.layerBridge.customEditCommand(f"Delete {group.kind.label.lower()} ({group.description})"):
            # The waypoints leave the map in the same edit, so undo puts them back.
            for leaf in leaves(group.children):
                for waypoint in iterTaskWaypoints(leaf):
                    fid = self.layerBridge.featureIdForWaypointUuid(waypoint.uuid)
                    if fid is not None:
                        self.layerBridge.waypointLayer.deleteFeature(fid)
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _addGroupAt(self, group: TaskGroup, index: int, ownerUuid: UUID | None = None) -> None:
        # One leaf at a time through the task path, so the tracks link each leaf to its neighbours.
        children, group.children = group.children, []
        self._container(ownerUuid).insert(index, group)
        for row, child in enumerate(children):
            if isinstance(child, TaskGroup):
                self._addGroupAt(child, row, group.uuid)
            else:
                self._addTaskAt(child, row, group.uuid)
        self.groupAdded.emit(group.uuid, index)

    def _deleteGroupAt(self, index: int, ownerUuid: UUID | None = None) -> None:
        container = self._container(ownerUuid)
        group = container[index]
        children = list(group.children)
        for row in reversed(range(len(children))):
            if isinstance(children[row], TaskGroup):
                self._deleteGroupAt(row, group.uuid)
            else:
                self._deleteTaskAt(row, group.uuid)
        container.pop(index)
        # The undo command holds this group. It gets its children back for the re-add.
        group.children = children
        self.groupDeleted.emit(group.uuid, index)

    # TODO: accept index in addTask?
    def addTask(self, taskType: str, description: str,
                taskUuid: UUID | None = None,
                group: TaskGroup | None = None) -> None:
        taskCls = TaskRegistry.lookup(taskType)
        requiredFields = taskCls.requiredFields()

        if not requiredFields:
            # Task can be added directly
            task = taskCls(description=description, uuid=taskUuid or uuid4())
            self.addTaskInstance(task, group)
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
                    parentUuid = None if group is None else group.uuid,
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
        group = self.plan.findGroup(pendingTask.parentUuid)
        self.addTaskInstance(task, group)

    def addTaskInstance(self, task: Task, group: TaskGroup | None = None) -> None:
        cmd = AddTaskUndoCommand(self, task, group)

        text = f"Add task {task.type} ({task.description})"
        with self.layerBridge.customEditCommand(text):
            for waypoint in iterTaskWaypoints(task):
                feat = self.layerBridge._waypointToFeature(task.uuid, task.description, waypoint)
                self.layerBridge.waypointLayer.addFeature(feat)
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _container(self, groupUuid: UUID | None) -> list[MissionNode]:
        return self.plan.children_of(self.plan.findGroup(groupUuid))

    def _addTaskAt(self, task: Task, index: int, groupUuid: UUID | None = None) -> None:
        self.beforeTaskAdded.emit(task.uuid, index)

        self._container(groupUuid).insert(index, task)
        self.index.registerTask(task)

        self.taskAdded.emit(task.uuid, index)

    def deleteTask(self, task: Task) -> None:
        location = self.plan.locate(task)
        if location is None:
            return
        cmd = DeleteTaskUndoCommand(self, task, location[0])

        text = f"Delete task {task.type} ({task.description})"
        with self.layerBridge.customEditCommand(text):
            for waypoint in iterTaskWaypoints(task):
                fid = self.layerBridge.featureIdForWaypointUuid(waypoint.uuid)
                if fid is not None:
                    self.layerBridge.waypointLayer.deleteFeature(fid)
            self._keepalive_undo.append(cmd)
            self.layerBridge.waypointLayer.undoStack().push(cmd)

    def _deleteTaskAt(self, index: int, groupUuid: UUID | None = None) -> None:
        container = self._container(groupUuid)
        task = container[index]

        # Listeners still need the task in the plan to find its neighbours.
        self.beforeTaskDeleted.emit(task.uuid)

        container.pop(index)
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
            self.deleteTask(task)
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
