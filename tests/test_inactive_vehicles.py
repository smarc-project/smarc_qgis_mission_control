from types import SimpleNamespace

import pytest

from qgis.PyQt.QtTest import QSignalSpy, QTest

from src.context.FleetState import INACTIVE_CHECK_INTERVAL, FleetState
from src.context.MqttService import MqttService, VehicleHeartbeatEvent
from src.ui.widgets.FleetControlWidget import FleetControlWidget
from src.ui.widgets.LiveViewWidget import LiveViewWidget
from src.ui.widgets.VehicleCardWidget import VehicleCardWidget
from src.ui.widgets.VehicleLiveViewWidget import VehicleLiveViewWidget

SAM = "waraps/unit/subsurface/simulation/sam1"
LOLO = "waraps/unit/subsurface/simulation/lolo1"


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class _MapManager:
    def onLookAtRequested(self, topic): ...
    def onMapColorChanged(self, topic, color): ...
    def onShowOnMapChanged(self, topic, shown): ...
    def clearAllVehicleMarkers(self): ...


@pytest.fixture
def fleet(qgis_app):
    mqtt = MqttService(None)
    clock = _Clock()
    state = FleetState(mqtt, None, clock=clock)
    state.setInactiveTimeout(60)

    def hear(topic):
        mqtt.vehicleHeartbeat.emit(VehicleHeartbeatEvent(topic, mode="auto"))

    def receive(topic, subtopic, payload):
        message = SimpleNamespace(topic=f"{topic}/{subtopic}", payload=payload)
        mqtt.onMqttMessage(None, None, message)

    def relay(topic, sensor, payload):
        receive(topic, f"sensor/{sensor}", payload)

    return SimpleNamespace(state=state, clock=clock, hear=hear, relay=relay, receive=receive)


def _sweep():
    QTest.qWait(INACTIVE_CHECK_INTERVAL + 200)


def test_silent_vehicle_expires_once_and_returns_when_heard(fleet):
    expired = QSignalSpy(fleet.state.vehicleExpired)
    returned = QSignalSpy(fleet.state.vehicleReturned)
    fleet.hear(SAM)
    fleet.hear(LOLO)

    fleet.clock.now += 30
    fleet.hear(LOLO)
    fleet.clock.now += 40
    _sweep()
    _sweep()

    assert [list(e) for e in expired] == [[SAM]]
    assert not fleet.state.isActive(SAM)
    assert fleet.state.isActive(LOLO)

    fleet.hear(SAM)
    assert [list(r) for r in returned] == [[SAM]]
    assert fleet.state.isActive(SAM)


def test_zero_timeout_brings_hidden_vehicles_back_and_hides_none(fleet):
    fleet.hear(SAM)
    fleet.clock.now += 100
    _sweep()
    assert not fleet.state.isActive(SAM)

    fleet.state.setInactiveTimeout(0)
    fleet.clock.now += 1000
    _sweep()

    assert fleet.state.isActive(SAM)


def test_relayed_sensors_keep_a_silent_vehicle_active(fleet):
    # Underwater: no heartbeat of its own, surface units fill in its depth.
    fleet.hear(LOLO)
    for _ in range(4):
        fleet.clock.now += 30
        fleet.relay(LOLO, "depth", b"12.5")
        _sweep()

    assert fleet.state.isActive(LOLO)

    fleet.clock.now += 61
    _sweep()
    assert not fleet.state.isActive(LOLO)


def test_commands_sent_to_a_silent_vehicle_do_not_keep_it_active(fleet):
    fleet.hear(LOLO)
    for _ in range(4):
        fleet.clock.now += 30
        fleet.receive(LOLO, "tst/command", b"{}")
        fleet.receive(LOLO, "exec/command", b"{}")

    _sweep()
    assert not fleet.state.isActive(LOLO)


def test_raising_the_timeout_brings_back_vehicles_inside_it(fleet):
    fleet.state.setInactiveTimeout(3)
    fleet.hear(SAM)
    fleet.clock.now += 10
    _sweep()
    assert not fleet.state.isActive(SAM)

    fleet.state.setInactiveTimeout(60)

    assert fleet.state.isActive(SAM)


def test_fleet_control_hides_and_deselects_a_silent_vehicle(fleet):
    panel = FleetControlWidget(fleet.state, _MapManager())
    fleet.hear(SAM)
    fleet.hear(LOLO)
    panel.selectAll()
    uploads = QSignalSpy(panel.uploadMissionPlanRequested)

    fleet.clock.now += 50
    fleet.hear(LOLO)
    fleet.clock.now += 20
    _sweep()

    layout = panel.ui.vehicleListVLayout
    cards = dict(zip((SAM, LOLO), (layout.itemAt(i).widget() for i in range(2))))
    assert all(isinstance(c, VehicleCardWidget) for c in cards.values())
    assert cards[SAM].isHidden() and not cards[SAM].isChecked()
    assert not cards[LOLO].isHidden()
    assert panel.ui.vehiclesSelectedLabel.text() == "All (1) vehicles selected · 1 silent, hidden"
    panel.ui.uploadMissionPlanButton.click()
    assert list(uploads[0]) == [{LOLO}]

    fleet.hear(SAM)
    assert not cards[SAM].isHidden() and not cards[SAM].isChecked()
    assert panel.ui.vehiclesSelectedLabel.text() == "1 vehicle selected"


def test_live_view_hides_the_row_but_keeps_it_on_the_map(fleet):
    panel = LiveViewWidget(SimpleNamespace(state=fleet.state, mapManager=_MapManager()))
    fleet.hear(SAM)
    [row] = panel.findChildren(VehicleLiveViewWidget)
    row.setChecked(True)

    fleet.clock.now += 61
    _sweep()

    assert row.isHidden()
    assert row.isChecked()
    assert not panel.ui.selectAllButton.isEnabled()

    # Deselect all still reaches it, so its last position can leave the map.
    shownOnMap = QSignalSpy(row.showOnMapChanged)
    panel.ui.deselectAllButton.click()
    assert not row.isChecked()
    assert [list(e) for e in shownOnMap] == [[SAM, False]]
    assert not panel.ui.deselectAllButton.isEnabled()

    fleet.hear(SAM)
    assert not row.isHidden()
