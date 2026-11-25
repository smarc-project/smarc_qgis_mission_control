"""Turn waypoints around their centre on the map, keeping their distances.

Waypoints are stored in latitude/longitude. Turning them in degrees, as QGIS's own
Rotate Feature(s) does, stretches the mission, because a degree of longitude is
shorter than a degree of latitude away from the equator. The turn is done in
metres instead, on a projection centred on the waypoints.
"""
import math
from uuid import UUID

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent, QgsMapTool, QgsRubberBand

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QKeyEvent

from .mapcoords import WGS84, mapToWgs84, wgs84ToMap

# Blue, so the preview never reads as the (red) waypoints themselves.
PREVIEW_COLOUR = QColor(0x20, 0x70, 0xE0)


class WaypointRotation:
    """Positions (lon/lat) turned about their centre, in metres."""

    def __init__(self, positions: dict[UUID, QgsPointXY]):
        self._positions = positions
        n = len(positions)
        self.centre = QgsPointXY(sum(p.x() for p in positions.values()) / n,
                                 sum(p.y() for p in positions.values()) / n)
        # Azimuthal equidistant: distances and bearings from the centre are true.
        local = QgsCoordinateReferenceSystem.fromProj(
            f"+proj=aeqd +lat_0={self.centre.y()} +lon_0={self.centre.x()} "
            "+datum=WGS84 +units=m +no_defs")
        context = QgsProject.instance().transformContext()
        self._toLocal = QgsCoordinateTransform(WGS84, local, context)
        self._toLonLat = QgsCoordinateTransform(local, WGS84, context)

    def angleTo(self, lonLat: QgsPointXY) -> float:
        """Direction from the centre to a point, in degrees counter-clockwise from east."""
        p = self._toLocal.transform(lonLat)
        return math.degrees(math.atan2(p.y(), p.x()))

    def turned(self, degrees: float) -> dict[UUID, QgsPointXY]:
        """Every position turned counter-clockwise by `degrees` about the centre."""
        c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        out = {}
        for uuid, lonLat in self._positions.items():
            p = self._toLocal.transform(lonLat)
            out[uuid] = self._toLonLat.transform(
                QgsPointXY(p.x() * c - p.y() * s, p.x() * s + p.y() * c))
        return out


class RotateWaypointsMapTool(QgsMapTool):
    """Click, move to turn the waypoints, click again to drop. Right-click or Esc cancels."""

    # UUID -> new position (lon/lat), emitted on the second click.
    rotated = pyqtSignal(dict)

    def __init__(self, canvas: QgsMapCanvas):
        super().__init__(canvas)
        self._rotation: WaypointRotation | None = None
        self._startAngle: float | None = None
        self._preview: tuple[QgsRubberBand, QgsRubberBand] | None = None

    def configure(self, positions: dict[UUID, QgsPointXY]) -> None:
        self._rotation = WaypointRotation(positions)
        self._startAngle = None

    def _lonLat(self, e: QgsMapMouseEvent) -> QgsPointXY:
        return mapToWgs84(self.canvas(), self.toMapCoordinates(e.pos()))

    def _band(self, geometryType) -> QgsRubberBand:
        band = QgsRubberBand(self.canvas(), geometryType)
        band.setColor(PREVIEW_COLOUR)
        return band

    def _showPreview(self, positions: dict[UUID, QgsPointXY]) -> None:
        """The turned path, dashed, with a hollow ring at each waypoint, in waypoint order."""
        if self._preview is None:
            path = self._band(QgsWkbTypes.LineGeometry)
            path.setWidth(2)
            path.setLineStyle(Qt.DashLine)
            rings = self._band(QgsWkbTypes.PointGeometry)
            rings.setIcon(QgsRubberBand.ICON_CIRCLE)
            rings.setIconSize(12)
            rings.setWidth(2)
            rings.setFillColor(QColor(0, 0, 0, 0))
            self._preview = (path, rings)
        points = [wgs84ToMap(self.canvas(), p) for p in positions.values()]
        for band in self._preview:
            band.reset(band.asGeometry().type())
            for point in points:
                band.addPoint(point, False)
            band.updatePosition()
            band.update()
            band.show()

    def _clearPreview(self) -> None:
        if self._preview is not None:
            for band in self._preview:
                self.canvas().scene().removeItem(band)
            self._preview = None

    def _finish(self) -> None:
        self._clearPreview()
        self._startAngle = None
        # Releasing the button puts the previous map tool back (MissionMapManager).
        if self.action() is not None:
            self.action().setChecked(False)
        else:
            self.canvas().unsetMapTool(self)

    def canvasMoveEvent(self, e: QgsMapMouseEvent) -> None:
        if self._rotation is None or self._startAngle is None:
            return
        turn = self._rotation.angleTo(self._lonLat(e)) - self._startAngle
        self._showPreview(self._rotation.turned(turn))

    def canvasReleaseEvent(self, e: QgsMapMouseEvent) -> None:
        if self._rotation is None:
            return
        if e.button() == Qt.RightButton:
            self._finish()
        elif e.button() == Qt.LeftButton:
            angle = self._rotation.angleTo(self._lonLat(e))
            if self._startAngle is None:
                self._startAngle = angle
                self._showPreview(self._rotation.turned(0.0))
            else:
                turned = self._rotation.turned(angle - self._startAngle)
                self._finish()
                self.rotated.emit(turned)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key_Escape:
            self._finish()

    def deactivate(self) -> None:
        self._clearPreview()
        self._startAngle = None
        super().deactivate()
