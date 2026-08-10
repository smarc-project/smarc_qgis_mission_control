from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from qgis.core import (  #QgsTextBackgroundSettings,
    QgsFeature,
    QgsFeatureRenderer,
    QgsField,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsPalLayerSettings,
    QgsPointXY,
    QgsProject,
    QgsProperty,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsTextFormat,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)

from qgis.PyQt.QtCore import QObject, QVariant, pyqtSignal, pyqtSlot  #, QSizeF
from qgis.PyQt.QtGui import QColor

from ..compat import StrEnum, assert_never
from ..domain.missionplan import MissionPlan
from ..domain.tasks import Task
from ..domain.taskspatial import iterTaskWaypoints
from ..domain.waypoints import Waypoint
from .MissionTracks import MissionTracks

__all__ = ["MissionLayerBridge"]

@dataclass
class JournalEntry:
    fid: int

@dataclass
class FeatureAddedEntry(JournalEntry):
    taskUuid: UUID
    description: str
    waypointUuid: UUID
    latitude: float
    longitude: float

@dataclass
class FeatureDeletedEntry(JournalEntry):
    waypointUuid: UUID

@dataclass
class FeatureMovedEntry(JournalEntry):
    waypointUuid: UUID
    latitude: float
    longitude: float

class MissionLayerBridge(QObject):
    class State(StrEnum):
        DEFAULT = 'default'
        QGIS_EDIT_COMMAND = 'qgis-edit-command'
        CUSTOM_EDIT_COMMAND = 'custom-edit-command'
        REPLAYING_QGIS_COMMAND = 'replaying-qgis-command'

    SMARC_GROUP_NAME = 'SMaRCMissions'
    # TODO: centralized place for these
    COLOR_SELECTED_TASK = QColor("#D81B60")
    COLOR_INACTIVE = QColor("#666666")
    COLOR_ACTIVE = QColor("#7040A0")

    waypointMoved = pyqtSignal(UUID, QgsPointXY)
    waypointAdded = pyqtSignal(UUID, UUID, QgsPointXY)
    waypointDeleted = pyqtSignal(UUID)

    _fidToWaypointUuid: dict[int, UUID]
    _waypointUuidToFid: dict[UUID, int]
    _state: State
    _journal: list[JournalEntry]

    _layerGroup: QgsLayerTreeGroup
    waypointLayer: QgsVectorLayer
    tracks: MissionTracks

    def __init__(self, plan: MissionPlan, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self._fidToWaypointUuid = {}
        self._waypointUuidToFid = {}
        self._state = self.State.DEFAULT
        self._journal = []

        self._setupLayerGroup(plan.uuid)
        self._initializeLayers(plan.uuid)
        self._populateLayers(plan)

        self.waypointLayer.setMapTipTemplate(
            '<b>Tolerance:</b> [% "tolerance" %] m'
        )

    def _setupLayerGroup(self, planUuid: UUID) -> None:
        # Find or create the SMaRCMissions group at the top of the layer tree
        qgs = QgsProject.instance()
        root = qgs.layerTreeRoot()
        smarcgroup = root.findGroup(self.SMARC_GROUP_NAME)
        if smarcgroup is None:
            smarcgroup = root.insertGroup(0, self.SMARC_GROUP_NAME)

        # Find or create group for this mission plan
        name = f"{planUuid}"
        layerGroup = root.findGroup(name)
        if layerGroup is None:
            layerGroup = smarcgroup.insertGroup(0, name)
        else:
            # Make sure it's clear of any leftover layers
            print(layerGroup, layerGroup.findLayers())
            qgs.removeMapLayers([node.layer() for node in layerGroup.findLayers()])

        self._layerGroup = layerGroup

    def _createActiveRenderer(self) -> QgsFeatureRenderer:
        # Configure symbol for layer
        symbol = QgsSymbol.defaultSymbol(self.waypointLayer.geometryType())

        markerSymbolLayer = symbol.symbolLayer(0)
        markerSymbolLayer.setColor(self.COLOR_ACTIVE)
        markerSymbolLayer.setDataDefinedProperty(
            QgsSimpleMarkerSymbolLayer.PropertyFillColor,
            QgsProperty.fromExpression(f'''
                CASE WHEN
                    array_contains(@selected_task_uuids, "task-uuid")
                THEN '{self.COLOR_SELECTED_TASK.name()}'
                ELSE '{markerSymbolLayer.color().name()}' END
            ''')
        )
        markerSymbolLayer.setSize(2.0)
        markerSymbolLayer.setDataDefinedProperty(
            QgsSimpleMarkerSymbolLayer.PropertySize,
            QgsProperty.fromExpression(f'''
                CASE WHEN
                    array_contains(@selected_task_uuids, "task-uuid")
                THEN 3
                ELSE {markerSymbolLayer.size()} END
            ''')
        )

        # Stroke width driven by the "tolerance" field
        markerSymbolLayer.setStrokeWidthUnit(QgsUnitTypes.RenderUnit.RenderMetersInMapUnits)
        markerSymbolLayer.setStrokeWidth(0.0)  # base width
        markerSymbolLayer.setStrokeColor(QColor("grey"))
        markerSymbolLayer.setDataDefinedProperty(
            QgsSimpleMarkerSymbolLayer.PropertyStrokeColor,
            QgsProperty.fromExpression('set_color_part(\'grey\', \'alpha\', 64)') # set stroke opacity seperate from symbol fill opacity
        )
        markerSymbolLayer.setDataDefinedProperty(
            QgsSimpleMarkerSymbolLayer.PropertyStrokeWidth,
            QgsProperty.fromExpression('coalesce("tolerance",0) * 4') # such that stroke radius matches tolerance
        )

        return QgsSingleSymbolRenderer(symbol)

    def _createInactiveRenderer(self) -> QgsFeatureRenderer:
        # Configure symbol for layer
        symbol = QgsSymbol.defaultSymbol(self.waypointLayer.geometryType())

        markerSymbolLayer = symbol.symbolLayer(0)
        markerSymbolLayer.setColor(self.COLOR_INACTIVE)
        markerSymbolLayer.setSize(2.0)

        return QgsSingleSymbolRenderer(symbol)

    def setActive(self, active: bool = True) -> None:
        opacity = 1.0 if active else 0.4
        self.waypointLayer.setOpacity(opacity)

        self.waypointLayer.setLabelsEnabled(active)

        renderer = self._activeRenderer if active else self._inactiveRenderer
        # Need to clone the reusable renderer, since layer takes ownership of it
        self.waypointLayer.setRenderer(renderer.clone())
        self.waypointLayer.triggerRepaint()

    def _initializeLayers(self, planUuid: UUID) -> None:
        """
        Important: The default layer CRS for waypoint layers is set to EPSG:4326.

        This default is dictated by the vehicles. No reprojection of coordinates 
        needed as long as waypoint layer is initialized with EPSG:4326.
        """
        # TODO: Split this into a separate class like MissionTracks

        # Setup waypoint layer
        self.waypointLayer = QgsVectorLayer(
            'point?crs=epsg:4326', # IMPORTANT: layer crs set to espg:4326
            f'Waypoints',
            'memory'
        )
        self.waypointLayer.dataProvider().addAttributes([
            QgsField('waypoint-uuid', QVariant.String),
            QgsField('task-uuid', QVariant.String),
            QgsField('tolerance', QVariant.Double),
            QgsField('task-description', QVariant.String),
        ])
        self.waypointLayer.updateFields()

        # Label each waypoint with its parent task's description
        labelSettings = QgsPalLayerSettings()
        labelSettings.fieldName = "task-description"
        labelSettings.placement = QgsPalLayerSettings.Placement.AroundPoint
        # labelSettings.settings.distUnits = Qgis.RenderUnit.Millimeters
        labelSettings.dist = 1.5

        textFormat = QgsTextFormat()
        textFormat.setSize(8)

        ## alt. 1: set background color and opacity for the text label
            ## requires from qgis.core import QgsTextBackgroundSettings
            ## requires from qgis.PyQt.QtCore import QSizeF
        # background = QgsTextBackgroundSettings()
        # background.setEnabled(True)
        # background.setType(QgsTextBackgroundSettings.ShapeType.ShapeRectangle)
        # background.setFillColor(QColor("white"))
        # background.setOpacity(0.75)
        # background.setSize(QSizeF(0.5, 0))  # padding around the text, in mm by default
        # textFormat.setBackground(background)

        ## alt. 2: set a buffer around the text label
        buffer = textFormat.buffer()
        buffer.setEnabled(True)
        buffer.setColor(QColor("yellow"))
        buffer.setSize(1.5)
        buffer.setOpacity(0.50)
        textFormat.setBuffer(buffer)

        labelSettings.setFormat(textFormat)

        self.waypointLayer.setLabeling(QgsVectorLayerSimpleLabeling(labelSettings))
        self.waypointLayer.setLabelsEnabled(True)

        # Make the layer non-removable (by users)
        flags = self.waypointLayer.flags()
        flags &= ~self.waypointLayer.LayerFlag.Removable
        self.waypointLayer.setFlags(flags)

        self._activeRenderer = self._createActiveRenderer()
        self._inactiveRenderer = self._createInactiveRenderer()

        # Register the layer with QGIS and add it to the group
        QgsProject().instance().addMapLayer(self.waypointLayer, False)
        self._layerGroup.addLayer(self.waypointLayer)

        #TODO auto-select/highlight newly created layer

        # Register layer callbacks
        self.waypointLayer.featureAdded.connect(self.onFeatureAdded)
        self.waypointLayer.featureDeleted.connect(self.onFeatureDeleted)
        self.waypointLayer.geometryChanged.connect(self.onGeometryChanged)

        self.waypointLayer.editCommandStarted.connect(self.onEditCommandStarted)
        self.waypointLayer.editCommandEnded.connect(self.onEditCommandEnded)

        # Setup the tracks layer
        self.tracks = MissionTracks(self.parent(), self._layerGroup, self)

    def _populateLayers(self, plan: MissionPlan) -> None:
        for task in plan.tasks:
            self._importTask(task)

    def _importTask(self, task: Task) -> None:
        # Tasks without waypoints currently have no map presence
        for waypoint in iterTaskWaypoints(task):
            self._importWaypoint(task.uuid, task.description, waypoint)

    def _importWaypoint(self, taskUuid: UUID, taskDescription: str, waypoint: Waypoint) -> None:
        feat = self._waypointToFeature(taskUuid, taskDescription, waypoint)
        self.waypointLayer.dataProvider().addFeature(feat)

        self._fidToWaypointUuid[feat.id()] = waypoint.uuid
        self._waypointUuidToFid[waypoint.uuid] = feat.id()

    def _waypointToFeature(self, taskUuid: UUID, taskDescription: str, waypoint: Waypoint) -> QgsFeature:
        feat = QgsFeature(self.waypointLayer.fields())
        point = QgsPointXY(waypoint.longitude, waypoint.latitude)
        geom = QgsGeometry.fromPointXY(point)
        feat.setGeometry(geom)
        feat.setAttribute('task-uuid', str(taskUuid))
        feat.setAttribute('task-description', str(taskDescription))
        feat.setAttribute('waypoint-uuid', str(waypoint.uuid))
        feat.setAttribute('tolerance', float(waypoint.tolerance))

        return feat

    def featureIdForWaypointUuid(self, waypointUuid: UUID) -> int | None:
        return self._waypointUuidToFid.get(waypointUuid)

    def waypointUuidForFeatureId(self, featureId: int) -> UUID | None:
        return self._fidToWaypointUuid.get(featureId)

    def updateTaskDescriptionLabel(self, taskUuid: UUID, description: str) -> None:
        # TODO: maybe a bit of a hack
        fieldIdx = self.waypointLayer.fields().indexFromName('task-description')
        changes = {
            feat.id(): {fieldIdx: description}
            for feat in self.waypointLayer.getFeatures()
            if feat.attribute('task-uuid') == str(taskUuid)
        }
        if changes:
            self.waypointLayer.dataProvider().changeAttributeValues(changes)
            self.waypointLayer.triggerRepaint()

    def setWaypointAttribute(self, waypointUuid: UUID, attributeName: str, value: Any) -> None:
        fid = self.featureIdForWaypointUuid(waypointUuid)
        if fid is None:
            # TODO: Invalid mapping
            return

        fieldIdx = self.waypointLayer.fields().indexFromName(attributeName)
        if fieldIdx < 0:
            return

        # TODO: confirm editable?
        self.waypointLayer.changeAttributeValue(fid, fieldIdx, value)

    @pyqtSlot(str)
    def onEditCommandStarted(self, text: str):
        print('onEditCommandStarted', text)
        if self._state is self.State.DEFAULT:
            self._state = self.State.QGIS_EDIT_COMMAND

    @pyqtSlot('QgsFeatureId')
    def onFeatureAdded(self, fid: int) -> None:
        print('onFeatureAdded', fid)
        feat = self.waypointLayer.getFeature(fid)
        waypointUuid = UUID(feat.attribute('waypoint-uuid'))

        self._fidToWaypointUuid[fid] = waypointUuid
        self._waypointUuidToFid[waypointUuid] = fid

        match self._state:
            case self.State.DEFAULT:
                ...
            case self.State.QGIS_EDIT_COMMAND:
                taskUuid = UUID(feat.attribute('task-uuid'))
                description = feat.attribute('task-description')
                point = feat.geometry().asPoint()
                entry = FeatureAddedEntry(fid, taskUuid, description, waypointUuid, point.y(),
                                          point.x())
                self._journal.append(entry)
            case self.State.CUSTOM_EDIT_COMMAND:
                ...
            case self.State.REPLAYING_QGIS_COMMAND:
                ...
            case _ as unreachable:
                assert_never(unreachable)

    @pyqtSlot('QgsFeatureId', QgsGeometry)
    def onGeometryChanged(self, fid: int, geom: QgsGeometry) -> None:
        print('onGeometryChanged', fid, geom)

        match self._state:
            case self.State.DEFAULT:
                ...
            case self.State.QGIS_EDIT_COMMAND:
                waypointUuid = self.waypointUuidForFeatureId(fid)
                assert(waypointUuid is not None)
                feat = self.waypointLayer.getFeature(fid)
                point = feat.geometry().asPoint()
                entry = FeatureMovedEntry(fid, waypointUuid, point.y(), point.x())
                self._journal.append(entry)
            case self.State.CUSTOM_EDIT_COMMAND:
                ...
            case self.State.REPLAYING_QGIS_COMMAND:
                ...
            case _ as unreachable:
                assert_never(unreachable)

    @pyqtSlot('QgsFeatureId')
    def onFeatureDeleted(self, fid: int) -> None:
        print('onFeatureDeleted', fid)

        waypointUuid = self.waypointUuidForFeatureId(fid)
        assert(waypointUuid is not None)

        match self._state:
            case self.State.DEFAULT:
                ...
            case self.State.QGIS_EDIT_COMMAND:
                entry = FeatureDeletedEntry(fid, waypointUuid)
                self._journal.append(entry)
            case self.State.CUSTOM_EDIT_COMMAND:
                ...
            case self.State.REPLAYING_QGIS_COMMAND:
                ...
            case _ as unreachable:
                assert_never(unreachable)

        del self._waypointUuidToFid[waypointUuid]
        del self._fidToWaypointUuid[fid]

    @pyqtSlot()
    def onEditCommandEnded(self):
        print('onEditCommandEnded')
        if self._state is not self.State.QGIS_EDIT_COMMAND:
            return

        if not len(self._journal):
            self._state = self.State.DEFAULT
            return

        self._state = self.State.REPLAYING_QGIS_COMMAND

        # Get rid of the command which just happened
        self.waypointLayer.undoStack().undo()

        # TODO: more specific text
        self.waypointLayer.beginEditCommand("Modify waypoints")

        waypointUuid: UUID | None
        for entry in self._journal:
            print(entry)
            match entry:
                case FeatureAddedEntry(fid, taskUuid, description, waypointUuid, latitude, longitude):
                    assert(waypointUuid)
                    self.parent().addWaypoint(taskUuid, description, latitude, longitude, waypointUuid)
                case FeatureDeletedEntry(fid, waypointUuid):
                    # Deleting one fixed waypoint may delete its entire task, including
                    # other features in the same QGIS edit command.
                    if self.parent().index.waypointByUuid(waypointUuid) is not None:
                        self.parent().deleteWaypoint(waypointUuid)
                case FeatureMovedEntry(fid, waypointUuid, latitude, longitude):
                    if self.parent().index.waypointByUuid(waypointUuid) is not None:
                        self.parent().setWaypointPosition(
                            waypointUuid, latitude, longitude)

        self._journal = []
        self._state = self.State.DEFAULT

        self.waypointLayer.endEditCommand()

    @contextmanager
    def customEditCommand(self, text: str):
        oldState = self._state
        self._state = self.State.CUSTOM_EDIT_COMMAND
        self.waypointLayer.beginEditCommand(text)
        try:
            yield
        except:
            self.waypointLayer.destroyEditCommand()
            raise
        else:
            self.waypointLayer.endEditCommand()
        finally:
            self._state = oldState

    def moveWaypointFeature(self, waypointUuid: UUID, latitude: float,
                            longitude: float):
        fid = self.featureIdForWaypointUuid(waypointUuid)
        if fid is None:
            # TODO: Invalid mapping
            return

        # TODO: confirm editable?
        point = QgsPointXY(longitude, latitude)
        self.waypointLayer.changeGeometry(fid, QgsGeometry.fromPointXY(point))

    def cleanup(self) -> None:
        qgs = QgsProject.instance()

        try:
            layerId = self.waypointLayer.id()
        except RuntimeError:
            # Layer may have been removed externally, e.g. during QGIS shutdown
            pass
        else:
            qgs.removeMapLayer(layerId)

        try:
            layerId = self.tracks._layer.id()
        except RuntimeError:
            # Layer may have been removed externally, e.g. during QGIS shutdown
            pass
        else:
            qgs.removeMapLayer(layerId)

        root = QgsProject.instance().layerTreeRoot()

        self._layerGroup.parent().removeChildNode(self._layerGroup)
