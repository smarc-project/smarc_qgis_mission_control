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
def fleetState(qgis_app):
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


def test_silent_vehicle_expires_once_and_returns_when_heard(fleetState):
    expired = QSignalSpy(fleetState.state.vehicleExpired)
    returned = QSignalSpy(fleetState.state.vehicleReturned)
    fleetState.hear(SAM)
    fleetState.hear(LOLO)

    fleetState.clock.now += 30
    fleetState.hear(LOLO)
    fleetState.clock.now += 40
    _sweep()
    _sweep()

    assert [list(e) for e in expired] == [[SAM]]
    assert not fleetState.state.isActive(SAM)
    assert fleetState.state.isActive(LOLO)

    fleetState.hear(SAM)
    assert [list(r) for r in returned] == [[SAM]]
    assert fleetState.state.isActive(SAM)


def test_zero_timeout_brings_hidden_vehicles_back_and_hides_none(fleetState):
    fleetState.hear(SAM)
    fleetState.clock.now += 100
    _sweep()
    assert not fleetState.state.isActive(SAM)

    fleetState.state.setInactiveTimeout(0)
    fleetState.clock.now += 1000
    _sweep()

    assert fleetState.state.isActive(SAM)


def test_relayed_sensors_keep_a_silent_vehicle_active(fleetState):
    # Underwater: no heartbeat of its own, surface units fill in its depth.
    fleetState.hear(LOLO)
    for _ in range(4):
        fleetState.clock.now += 30
        fleetState.relay(LOLO, "depth", b"12.5")
        _sweep()

    assert fleetState.state.isActive(LOLO)

    fleetState.clock.now += 61
    _sweep()
    assert not fleetState.state.isActive(LOLO)


def test_commands_sent_to_a_silent_vehicle_do_not_keep_it_active(fleetState):
    fleetState.hear(LOLO)
    for _ in range(4):
        fleetState.clock.now += 30
        fleetState.receive(LOLO, "tst/command", b"{}")
        fleetState.receive(LOLO, "exec/command", b"{}")

    _sweep()
    assert not fleetState.state.isActive(LOLO)


def test_raising_the_timeout_brings_back_vehicles_inside_it(fleetState):
    fleetState.state.setInactiveTimeout(3)
    fleetState.hear(SAM)
    fleetState.clock.now += 10
    _sweep()
    assert not fleetState.state.isActive(SAM)

    fleetState.state.setInactiveTimeout(60)

    assert fleetState.state.isActive(SAM)


def test_fleet_control_hides_and_deselects_a_silent_vehicle(fleetState):
    panel = FleetControlWidget(fleetState.state, _MapManager())
    fleetState.hear(SAM)
    fleetState.hear(LOLO)
    panel.selectAll()
    uploads = QSignalSpy(panel.uploadMissionPlanRequested)

    fleetState.clock.now += 50
    fleetState.hear(LOLO)
    fleetState.clock.now += 20
    _sweep()

    layout = panel.ui.vehicleListVLayout
    cards = dict(zip((SAM, LOLO), (layout.itemAt(i).widget() for i in range(2))))
    assert all(isinstance(c, VehicleCardWidget) for c in cards.values())
    assert cards[SAM].isHidden() and not cards[SAM].isChecked()
    assert not cards[LOLO].isHidden()
    assert panel.ui.vehiclesSelectedLabel.text() == "All (1) vehicles selected · 1 silent, hidden"
    panel.ui.uploadMissionPlanButton.click()
    assert list(uploads[0]) == [{LOLO}]

    fleetState.hear(SAM)
    assert not cards[SAM].isHidden() and not cards[SAM].isChecked()
    assert panel.ui.vehiclesSelectedLabel.text() == "1 vehicle selected"


def test_live_view_hides_the_row_but_keeps_it_on_the_map(fleetState):
    panel = LiveViewWidget(SimpleNamespace(state=fleetState.state, mapManager=_MapManager()))
    fleetState.hear(SAM)
    [row] = panel.findChildren(VehicleLiveViewWidget)
    row.setChecked(True)

    fleetState.clock.now += 61
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

    fleetState.hear(SAM)
    assert not row.isHidden()
