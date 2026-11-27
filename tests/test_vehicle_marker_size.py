from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsMapRendererSequentialJob,
    QgsMapSettings,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
)
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor

# The marker SVGs live in the plugin's Qt resources.
import src.ui.generated.resources_rc  # noqa: F401
from test_vehicle_tracks import SAM, fleet  # noqa: F401  (pytest fixture)

CANVAS_PX = 400
DPI = 96
PX_PER_MM = DPI / 25.4
# SAM sits at lon 11, lat 59; web mercator keeps the extent square on screen.
WEB_MERCATOR = QgsCoordinateReferenceSystem("EPSG:3857")


def _markerWidthPx(mapWidth: float) -> int:
    """Render SAM's marker alone on a map `mapWidth` mercator meters wide; return its width in pixels."""
    [layer] = QgsProject.instance().mapLayersByName("SMaRCVehiclePositionLayer")
    settings = QgsMapSettings()
    settings.setLayers([layer])
    settings.setDestinationCrs(WEB_MERCATOR)
    settings.setOutputSize(QSize(CANVAS_PX, CANVAS_PX))
    settings.setOutputDpi(DPI)
    settings.setBackgroundColor(QColor("white"))
    centre = settings.layerToMapCoordinates(layer, QgsPointXY(11.0, 59.0))
    half = mapWidth / 2
    settings.setExtent(QgsRectangle(centre.x() - half, centre.y() - half,
                                    centre.x() + half, centre.y() + half))
    job = QgsMapRendererSequentialJob(settings)
    job.start()
    job.waitForFinished()
    image = job.renderedImage()
    white = QColor("white").rgb()
    columns = [x for x in range(image.width())
               if any(image.pixel(x, y) != white for y in range(image.height()))]
    return columns[-1] - columns[0] + 1 if columns else 0


def test_vehicle_marker_stays_visible_zoomed_out(fleet):  # noqa: F811
    states, _ = fleet
    states.move(SAM, 0.0, 59.0)

    # About 1:150 000 on this canvas: a few meters of vehicle is under a pixel.
    assert _markerWidthPx(20_000.0) >= 3 * PX_PER_MM


def test_vehicle_marker_does_not_fill_the_map_zoomed_in(fleet):  # noqa: F811
    states, _ = fleet
    states.move(SAM, 0.0, 59.0)

    # About 1:100: unlimited, a vehicle in meters would cover most of the map.
    assert _markerWidthPx(15.0) <= 12 * PX_PER_MM
