from types import SimpleNamespace

import pytest

from src.context.FleetState import FleetState
from src.context.MqttService import MqttService
from src.ui.widgets.FleetControlWidget import FleetControlWidget
from src.ui.widgets.LiveViewWidget import LiveViewWidget
from src.ui.widgets.VehicleCardWidget import VehicleCardWidget
from src.ui.widgets.VehicleLiveViewWidget import VehicleLiveViewWidget

SAM = "waraps/unit/subsurface/simulation/sam1"


class _MapManager:
    def onLookAtRequested(self, topic): ...
    def onMapColorChanged(self, topic, color): ...
    def onShowOnMapChanged(self, topic, shown): ...
    def clearAllVehicleMarkers(self): ...


@pytest.fixture
def lists(qgis_app):
    mqtt = MqttService(None)
    state = FleetState(mqtt, None)
    fleet = FleetControlWidget(state, _MapManager())
    live = LiveViewWidget(SimpleNamespace(state=state, mapManager=_MapManager()))

    def receive(subtopic, payload):
        mqtt.onMqttMessage(None, None, SimpleNamespace(topic=f"{SAM}/{subtopic}", payload=payload))

    return SimpleNamespace(fleet=fleet, live=live, receive=receive)


def _modeLabels(lists):
    [card] = lists.fleet.findChildren(VehicleCardWidget)
    [row] = lists.live.findChildren(VehicleLiveViewWidget)
    return card.ui.modeLabel.text(), row.ui.modeLabel.text()


def test_heartbeat_alone_shows_the_mode(lists):
    lists.receive("heartbeat", b'{"name": "sam1"}')

    assert _modeLabels(lists) == ("(simulation)", "(simulation)")


def test_no_placeholder_before_the_mode_is_known(lists):
    lists.receive("sensor/position",
                  b'{"latitude": 58.0, "longitude": 11.0, "altitude": 0, "type": "GeoPoint"}')

    assert _modeLabels(lists) == ("", "")
