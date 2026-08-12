from dataclasses import dataclass
from uuid import UUID

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
)
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent, QgsMapTool, QgsRubberBand
from qgis.utils import iface

from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QAction

from ..domain.tasks import PendingWaypointTask

__all__ = ["MissionMapManager"]

class MyMapTool(QgsMapTool):
    mapClicked = pyqtSignal(QgsPointXY, Qt.MouseButton)

    def _toWgs84(self, point: QgsPointXY) -> QgsPointXY:
        """Helper to transform a point from map canvas CRS to EPSG:4326 (required)."""
        canvas_crs = self.canvas().mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if canvas_crs == wgs84:
            return point
        transform = QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance())
        return transform.transform(point)

    def canvasReleaseEvent(self, e: QgsMapMouseEvent):
        point = self._toWgs84(self.toMapCoordinates(e.pos()))
        if e.button() == Qt.MouseButton.RightButton:
            # Disable self
            ...
        self.mapClicked.emit(point, e.button())

class AddWaypointTool(MyMapTool):
    @dataclass
    class Configuration:
        insertAt: int
        taskUuid: UUID
        fieldName: str
        anchorBefore: QgsPointXY | None
        anchorAfter: QgsPointXY | None

    _config: Configuration | None = None
    _leftRb: QgsRubberBand | None = None
    _rightRb: QgsRubberBand | None = None

    def configure(self, config: Configuration):
        self._config = config

    def taskUuid(self) -> UUID | None:
        if self._config is None:
            return None
        return self._config.taskUuid

    def fieldName(self) -> str | None:
        if self._config is None:
            return None
        return self._config.fieldName

class PickInitialWaypointTool(MyMapTool):
    @dataclass
    class Configuration:
        pendingTask: PendingWaypointTask

    _config: Configuration | None = None

    def configure(self, config: Configuration):
        self._config = config

    def pendingTask(self) -> PendingWaypointTask | None:
        if self._config is None:
            return None
        return self._config.pendingTask

class SelectLocationMapTool(MyMapTool):
    @dataclass
    class Configuration:
        waypointUuid: UUID
        anchorBefore: QgsPointXY | None
        anchorAfter: QgsPointXY | None

    _config: Configuration | None = None
    _leftRb: QgsRubberBand | None = None
    _rightRb: QgsRubberBand | None = None

    def _cleanupRubberBands(self):
        if self._leftRb is not None:
            self.canvas().scene().removeItem(self._leftRb)
            self._leftRb = None
        if self._rightRb is not None:
            self.canvas().scene().removeItem(self._rightRb)
            self._rightRb = None

    def configure(self, config: Configuration):
        self._config = config

    def activate(self):
        self._cleanupRubberBands()

        if self._config and self._config.anchorBefore:
            self._leftRb = QgsRubberBand(self.canvas())
            self._leftRb.setColor(QColor(0x7F, 0x7F, 0x7F, 200))
            self._leftRb.addPoint(self._config.anchorBefore)
            self._leftRb.addPoint(QgsPointXY(0, 0))
            self._leftRb.hide()

        if self._config and self._config.anchorAfter:
            self._rightRb = QgsRubberBand(self.canvas())
            self._rightRb.setColor(QColor(0, 0x7F, 0x7F, 255))
            self._rightRb.addPoint(QgsPointXY(0, 0))
            self._rightRb.addPoint(self._config.anchorAfter)
            self._rightRb.hide()

        super().activate()

    def waypointUuid(self) -> UUID | None:
        if self._config is None:
            return None
        return self._config.waypointUuid

    def deactivate(self):
        self._cleanupRubberBands()
        self._config = None

        super().deactivate()

    def canvasMoveEvent(self, e: QgsMapMouseEvent):
        point = self.toMapCoordinates(e.pos())
        if self._leftRb is not None:
            self._leftRb.show()
            self._leftRb.movePoint(1, point)
        if self._rightRb is not None:
            self._rightRb.show()
            self._rightRb.movePoint(0, point)

class MissionMapManager(QObject):
    _canvas: QgsMapCanvas

    _selectLocationTool: SelectLocationMapTool
    _pickInitialWaypointTool: PickInitialWaypointTool
    _addWaypointTool: AddWaypointTool

    initialWaypointPicked = pyqtSignal(PendingWaypointTask, QgsPointXY)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._canvas = iface.mapCanvas()
        self._previousTool = self._canvas.mapTool()

        self._selectLocationTool = SelectLocationMapTool(self._canvas)
        self._selectLocationTool.mapClicked.connect(
            self.onSelectLocationToolMapClicked
        )

        self._pickInitialWaypointTool = PickInitialWaypointTool(self._canvas)
        self._pickInitialWaypointTool.mapClicked.connect(
            self.onPickInitialWaypointToolMapClicked
        )

        self._addWaypointTool = AddWaypointTool(self._canvas)
        self._addWaypointTool.mapClicked.connect(
            self.onAddWaypointToolMapClicked
        )

    # Map Tools
    def onAddWaypointToolMapClicked(self, point: QgsPointXY, button: Qt.MouseButton):
        if button == Qt.MouseButton.RightButton:
            # Disable tool
            self._canvas.setMapTool(self._previousTool)
            self._addWaypointTool.setAction(None)
        elif button == Qt.MouseButton.LeftButton:
            # Add a new feature!
            doc = self.parent().activeDocument()
            if doc is None:
                # TODO: invalid mapping
                return

            taskUuid = self._addWaypointTool.taskUuid()
            fieldName = self._addWaypointTool.fieldName()
            if taskUuid is None or fieldName is None:
                # TODO: invalid mapping
                return

            task = doc.index.taskByUuid(taskUuid)
            if task is None:
                # TODO: invalid mapping
                return

            doc.addWaypoint(taskUuid, task.description, point.y(), point.x(), fieldName = fieldName)

    @pyqtSlot(QgsPointXY, Qt.MouseButton)
    def onSelectLocationToolMapClicked(self, point: QgsPointXY,
                                       button: Qt.MouseButton) -> None:
        if button == Qt.MouseButton.RightButton:
            # Disable selection tool
            self._canvas.setMapTool(self._previousTool)
            self._selectLocationTool.setAction(None)
        elif button == Qt.MouseButton.LeftButton:
            # Move the current waypoint
            waypointUuid = self._selectLocationTool.waypointUuid()
            if waypointUuid is None:
                # TODO: invalid mapping
                return
            doc = self.parent().activeDocument()
            if doc is None:
                # TODO: invalid mapping
                return

            doc.setWaypointPosition(waypointUuid, point.y(), point.x())

    def pickInitialWaypoint(self, pendingTask: PendingWaypointTask) -> None:
        self._previousTool = self._canvas.mapTool()
        config = PickInitialWaypointTool.Configuration(
            pendingTask = pendingTask
        )
        self._pickInitialWaypointTool.configure(config)
        self._canvas.setMapTool(self._pickInitialWaypointTool)

    @pyqtSlot(QgsPointXY, Qt.MouseButton)
    def onPickInitialWaypointToolMapClicked(self, point: QgsPointXY,
                                            button: Qt.MouseButton) -> None:
        if button == Qt.MouseButton.RightButton:
            # Disable the tool. No task will be created
            self._canvas.setMapTool(self._previousTool)
        elif button == Qt.MouseButton.LeftButton:
            # Add a new feature!
            pendingTask = self._pickInitialWaypointTool.pendingTask()
            if pendingTask is None:
                # TODO: invalid mapping
                return
            self.initialWaypointPicked.emit(pendingTask, point)

            # Done picking initial waypoint
            self._canvas.setMapTool(self._previousTool)

    # Model -> Layer
    @pyqtSlot(QAction, UUID, bool)
    def onSelectLocationRequested(self, action: QAction, waypointUuid: UUID,
                                  active: bool) -> None:
        if active:
            self._previousTool = self._canvas.mapTool()
            self._selectLocationTool.setAction(action)
            config = SelectLocationMapTool.Configuration(
                waypointUuid = waypointUuid,
                # TODO: figure out these points, diff colors too
                anchorBefore = None,
                anchorAfter = None,
            )
            self._selectLocationTool.configure(config)
            self._canvas.setMapTool(self._selectLocationTool)
        else:
            self._canvas.setMapTool(self._previousTool)
            self._selectLocationTool.setAction(None)

    @pyqtSlot(QAction, int, UUID, str, bool)
    def onAddWaypointRequested(self, action: QAction, insertAt: int, taskUuid: UUID,
                               fieldName: str, active: bool) -> None:
        if active:
            self._previousTool = self._canvas.mapTool()
            self._addWaypointTool.setAction(action)

            config = AddWaypointTool.Configuration(
                insertAt = insertAt,
                taskUuid = taskUuid,
                fieldName = fieldName,
                # TODO:
                anchorBefore = None,
                anchorAfter = None,
            )
            self._addWaypointTool.configure(config)

            self._canvas.setMapTool(self._addWaypointTool)
        else:
            self._canvas.setMapTool(self._previousTool)
            self._addWaypointTool.setAction(None)
