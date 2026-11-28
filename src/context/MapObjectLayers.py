import math
import time
from dataclasses import dataclass

from qgis.core import (
    Qgis,
    QgsDistanceArea,
    QgsFeature,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsLayerTreeGroup,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsProperty,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsSymbolLayer,
    QgsVectorLayer,
)

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject, QTimer, QVariant, pyqtSlot
from qgis.PyQt.QtGui import QColor

from ..domain.mapobjects import MapObject, MapObjectShape, parseMapObject
from .FleetMapManager import FleetMapManager

# Red is kept for no-go zones; a message's own `color` still wins.
DEFAULT_MAP_OBJECT_COLOR = '#1e90ff'
# Area fill opacity (0-255), so the map and the vehicles show through.
AREA_FILL_ALPHA = 60
POINT_SIZE_MM = 3.0
LINE_WIDTH_MM = 0.8
# Corners of the polygon a circle is drawn as.
CIRCLE_SEGMENTS = 72
EXPIRY_CHECK_INTERVAL_MS = 1000
LOG_TAG = 'SMaRC Mission Control'
# The colour a feature is drawn in: its own, or the default.
COLOR_EXPRESSION = f'coalesce("color", \'{DEFAULT_MAP_OBJECT_COLOR}\')'


@dataclass
class _DrawnMapObject:
    layer: QgsVectorLayer
    fid: int
    # time.monotonic() at which it leaves the map; None stays until replaced or cleared.
    expiresAt: float | None


class MapObjectLayers(QObject):
    """Draws WARA-PS map objects (points, paths, areas) on their own layers, by name."""

    GROUP_NAME = 'SMaRC map objects'
    POINT_LAYER_NAME = 'Map points'
    PATH_LAYER_NAME = 'Map paths'
    AREA_LAYER_NAME = 'Map areas'

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._group: QgsLayerTreeGroup | None = None
        self._layersByShape: dict[MapObjectShape, QgsVectorLayer] = {}
        self._drawn: dict[str, _DrawnMapObject] = {}
        # One timer for every object with a duration; a timer each would pile up
        # when something republishes markers at a high rate.
        self._expiryTimer = QTimer(self)
        self._expiryTimer.setInterval(EXPIRY_CHECK_INTERVAL_MS)
        self._expiryTimer.timeout.connect(self._removeExpiredNow)

    @pyqtSlot(str, bytes)
    def onMapObjectMessage(self, name: str, payload: bytes) -> None:
        """Draw, replace or (on an empty payload) clear the map object of that name."""
        if not payload:
            self.removeMapObject(name)
            return
        try:
            mapObject = parseMapObject(name, payload)
        except ValueError as e:
            QgsMessageLog.logMessage(
                f'Ignored map object {name}: {e}',
                LOG_TAG,
                Qgis.MessageLevel.Warning,
            )
            return
        self.showMapObject(mapObject, time.monotonic())

    def showMapObject(self, mapObject: MapObject, receivedAt: float) -> None:
        """Draw a map object, replacing the one with the same name."""
        self.removeMapObject(mapObject.name)
        layer = self._layerFor(mapObject.shape)

        feature = QgsFeature(layer.fields())
        feature.setGeometry(self._geometryOf(mapObject))
        feature['name'] = mapObject.name
        feature['color'] = mapObject.color
        _, [added] = layer.dataProvider().addFeatures([feature])
        layer.triggerRepaint()

        expiresAt = receivedAt + mapObject.duration if mapObject.duration > 0 else None
        self._drawn[mapObject.name] = _DrawnMapObject(layer, added.id(), expiresAt)
        if expiresAt is not None and not self._expiryTimer.isActive():
            self._expiryTimer.start()

    def removeMapObject(self, name: str) -> None:
        drawn = self._drawn.pop(name, None)
        # Its layer is gone if the user removed it or started a new project.
        if drawn is None or sip.isdeleted(drawn.layer):
            return
        drawn.layer.dataProvider().deleteFeatures([drawn.fid])
        drawn.layer.triggerRepaint()

    @pyqtSlot()
    def clearMapObjects(self) -> None:
        for name in list(self._drawn):
            self.removeMapObject(name)

    def removeExpired(self, now: float) -> None:
        """Remove the map objects whose duration has run out by `now` (time.monotonic())."""
        for name, drawn in list(self._drawn.items()):
            if drawn.expiresAt is not None and drawn.expiresAt <= now:
                self.removeMapObject(name)
        if not any(drawn.expiresAt is not None for drawn in self._drawn.values()):
            self._expiryTimer.stop()

    @pyqtSlot()
    def _removeExpiredNow(self) -> None:
        self.removeExpired(time.monotonic())

    def cleanup(self) -> None:
        self._expiryTimer.stop()
        self._removeLayers()

    def _removeLayers(self) -> None:
        """Take our layers and group out of the project, skipping any already deleted."""
        self._drawn.clear()
        qgs = QgsProject.instance()
        wasDirty = qgs.isDirty()
        for layer in set(self._layersByShape.values()):
            # Removed by hand, or by Project > New / Exit before plugins unload.
            if not sip.isdeleted(layer):
                qgs.removeMapLayer(layer.id())
        # A group left in the layer tree is removed during QGIS's own teardown,
        # after its layer panel is gone, and that crashes QGIS on quit (#148).
        if self._group is not None and not sip.isdeleted(self._group):
            self._group.parent().removeChildNode(self._group)
        qgs.setDirty(wasDirty)
        self._layersByShape.clear()
        self._group = None

    def _geometryOf(self, mapObject: MapObject) -> QgsGeometry:
        points = [QgsPointXY(lon, lat) for lat, lon in mapObject.latLons]
        if mapObject.shape == MapObjectShape.POINT:
            return QgsGeometry.fromPointXY(points[0])
        if mapObject.shape == MapObjectShape.PATH:
            return QgsGeometry.fromPolylineXY(points)
        if mapObject.shape == MapObjectShape.POLYGON:
            return QgsGeometry.fromPolygonXY([points])
        return QgsGeometry.fromPolygonXY([self._circleOutline(points[0], mapObject.radius)])

    def _circleOutline(self, centre: QgsPointXY, radius: float) -> list[QgsPointXY]:
        """A circle of `radius` metres on the WGS84 ellipsoid, as lon/lat corners."""
        ellipsoid = QgsDistanceArea()
        ellipsoid.setEllipsoid('WGS84')
        return [
            ellipsoid.computeSpheroidProject(
                centre,
                radius,
                2 * math.pi * corner / CIRCLE_SEGMENTS,
            )
            for corner in range(CIRCLE_SEGMENTS + 1)
        ]

    def _layerFor(self, shape: MapObjectShape) -> QgsVectorLayer:
        # Made on the first map object, so a session without any adds no empty
        # layers, and nothing is added before QGIS has finished starting.
        # Made again if the user removed any of them or started a new project;
        # what was drawn is gone then, and comes back as it is sent again.
        if not self._layersByShape or self._anyLayerDeleted():
            self._removeLayers()
            self._setupLayers()
        return self._layersByShape[shape]

    def _anyLayerDeleted(self) -> bool:
        return sip.isdeleted(self._group) or any(
            sip.isdeleted(layer) for layer in self._layersByShape.values()
        )

    def _groupIndex(self) -> int:
        """Just below the vehicle positions, so vehicles and missions draw on top."""
        root = QgsProject.instance().layerTreeRoot()
        for index, node in enumerate(root.children()):
            if node.name() == FleetMapManager.LAYER_NAME:
                return index + 1
        return 0

    def _setupLayers(self) -> None:
        qgs = QgsProject.instance()
        # Live map objects are not the user's work: adding their layers must not
        # make QGIS ask to save an otherwise untouched project on quit.
        wasDirty = qgs.isDirty()
        self._group = qgs.layerTreeRoot().insertGroup(self._groupIndex(), self.GROUP_NAME)

        pointLayer = self._addLayer('Point', self.POINT_LAYER_NAME, self._pointSymbol())
        pathLayer = self._addLayer('LineString', self.PATH_LAYER_NAME, self._pathSymbol())
        areaLayer = self._addLayer('Polygon', self.AREA_LAYER_NAME, self._areaSymbol())
        self._layersByShape = {
            MapObjectShape.POINT: pointLayer,
            MapObjectShape.PATH: pathLayer,
            MapObjectShape.POLYGON: areaLayer,
            # A circle is drawn as a polygon, and WARA-PS sends both on the same -A topic.
            MapObjectShape.CIRCLE: areaLayer,
        }
        qgs.setDirty(wasDirty)

    def _addLayer(
        self,
        geometryType: str,
        layerName: str,
        symbol: QgsSymbol,
    ) -> QgsVectorLayer:
        layer = QgsVectorLayer(f'{geometryType}?crs=EPSG:4326', layerName, 'memory')
        layer.dataProvider().addAttributes([
            QgsField('name', QVariant.String),
            QgsField('color', QVariant.String),
        ])
        layer.updateFields()
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.setMapTipTemplate('<b>Map object:</b> [% "name" %]')
        # Map objects come back from the broker (they are retained); skip QGIS's
        # "temporary scratch layers will be lost" warning for them.
        layer.setCustomProperty('skipMemoryLayersCheck', 1)
        QgsProject.instance().addMapLayer(layer, False)
        self._group.addLayer(layer)
        return layer

    # The symbols' own colours are what the layer tree's legend shows; each feature
    # is drawn in the colour its `color` field gives.
    def _pointSymbol(self) -> QgsMarkerSymbol:
        symbol = QgsMarkerSymbol.createSimple({
            'name': 'circle',
            'size': str(POINT_SIZE_MM),
            'color': DEFAULT_MAP_OBJECT_COLOR,
            'outline_color': 'white',
        })
        symbol.symbolLayer(0).setDataDefinedProperty(
            QgsSymbolLayer.Property.FillColor,
            QgsProperty.fromExpression(COLOR_EXPRESSION),
        )
        return symbol

    def _pathSymbol(self) -> QgsLineSymbol:
        symbol = QgsLineSymbol.createSimple({
            'line_width': str(LINE_WIDTH_MM),
            'line_color': DEFAULT_MAP_OBJECT_COLOR,
        })
        symbol.symbolLayer(0).setDataDefinedProperty(
            QgsSymbolLayer.Property.StrokeColor,
            QgsProperty.fromExpression(COLOR_EXPRESSION),
        )
        return symbol

    def _areaSymbol(self) -> QgsFillSymbol:
        fillColor = QColor(DEFAULT_MAP_OBJECT_COLOR)
        fillColor.setAlpha(AREA_FILL_ALPHA)
        symbol = QgsFillSymbol.createSimple({
            'outline_width': str(LINE_WIDTH_MM),
            'outline_color': DEFAULT_MAP_OBJECT_COLOR,
        })
        symbolLayer = symbol.symbolLayer(0)
        symbolLayer.setFillColor(fillColor)
        symbolLayer.setDataDefinedProperty(
            QgsSymbolLayer.Property.FillColor,
            QgsProperty.fromExpression(
                f"set_color_part({COLOR_EXPRESSION}, 'alpha', {AREA_FILL_ALPHA})"
            ),
        )
        symbolLayer.setDataDefinedProperty(
            QgsSymbolLayer.Property.StrokeColor,
            QgsProperty.fromExpression(COLOR_EXPRESSION),
        )
        return symbol
