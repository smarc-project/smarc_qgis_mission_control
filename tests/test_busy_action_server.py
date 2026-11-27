import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtTest import QSignalSpy
from qgis.PyQt.QtWidgets import QApplication, QMessageBox

from src.context.FleetState import FleetState
from src.context.MqttService import MqttService
from src.domain.missionplan import MissionPlan
from src.domain.tasks import LoiterTask, MoveToTask
from src.domain.waypoints import GeoPoint
from src.ui.widgets.FleetControlWidget import FleetControlWidget
from src.ui.widgets.MissionControlDockWidget import MissionControlDockWidget

SAM = "waraps/unit/subsurface/simulation/sam1"
RUNNING = UUID("0d6a4a8e-0000-4000-8000-000000000001")


class _MapManager:
    def onLookAtRequested(self, topic): ...


class _Client:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, topic: str, payload: str) -> None:
        self.published.append((topic, json.loads(payload)))


def _executionInfo(executing: list[dict]) -> bytes:
    # The officer's tst_execution_info, as waraps_officer.commands.dumps writes it.
    return json.dumps({
        "name": "sam1", "rate": 1.0, "type": "TSTExecutionInfo", "stamp": 0.0,
        "tasks-available": [
            {"name": "move-to", "signals": ["$abort"], "last_seen": 0.0,
             "ros_name": "/sam1/move_to"},
        ],
        "tasks-executing": executing,
    }).encode()


GO_TO_DOCK = {
    "task-uuid": str(RUNNING),
    "task-name": "move-to",
    "status": "running",
    "description": "Go to dock",
}


@pytest.fixture
def panel(qgis_app):
    mqtt = MqttService(None)
    state = FleetState(mqtt, None)
    plan = MissionPlan(name="seq", description="Survey", tasks=[
        MoveToTask(description="Go to start", waypoint=GeoPoint(latitude=58.25, longitude=11.45)),
        LoiterTask(description="Wait"),
    ])
    widget = FleetControlWidget(state, _MapManager())
    # The dock's own upload slot, so a click takes the one path: plan checks, busy check, send.
    dock = MissionControlDockWidget.__new__(MissionControlDockWidget)
    dock._missionContext = SimpleNamespace(activeDocument=lambda: SimpleNamespace(plan=plan))
    dock.ui = SimpleNamespace(tabFleetControl=widget)
    # The dock is not a constructed QObject, so PyQt will not connect to its slot directly.
    widget.uploadMissionPlanRequested.connect(
        lambda vehicleTopics: dock.onUploadMissionPlanRequested(vehicleTopics)
    )

    def receive(payload: bytes) -> None:
        message = SimpleNamespace(topic=f"{SAM}/tst_execution_info", payload=payload)
        mqtt.onMqttMessage(None, None, message)

    receive(_executionInfo([GO_TO_DOCK]))
    widget.selectAll()
    return SimpleNamespace(widget=widget, dock=dock, plan=plan, receive=receive)


def _answerBusyDialog(buttonText: str, seen: list[str]) -> None:
    """Click buttonText on the busy-server box once it is open, noting what it said."""
    def answer() -> None:
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        seen.append(f"{box.text()}\n{box.informativeText()}")
        [button] = [b for b in box.buttons() if b.text().replace("&", "") == buttonText]
        button.click()
    QTimer.singleShot(0, answer)


def test_start_on_busy_server_is_refused_with_the_reason(panel):
    uploads = QSignalSpy(panel.widget.sendMissionPlanRequested)
    aborts = QSignalSpy(panel.widget.abortTasksRequested)
    seen: list[str] = []

    _answerBusyDialog("Cancel", seen)
    panel.widget.ui.uploadMissionPlanButton.click()

    [text] = seen
    assert "sam1" in text and "move-to" in text and "Go to dock" in text
    assert len(uploads) == 0
    assert len(aborts) == 0


def test_override_confirms_aborts_then_starts_when_the_server_is_free(panel):
    uploads = QSignalSpy(panel.widget.sendMissionPlanRequested)
    aborts = QSignalSpy(panel.widget.abortTasksRequested)
    seen: list[str] = []

    _answerBusyDialog("Override", seen)
    panel.widget.ui.uploadMissionPlanButton.click()

    assert len(seen) == 1
    assert [list(a) for a in aborts] == [[{SAM: [RUNNING]}]]
    # The officer still lists the task while its server cancels it.
    panel.receive(_executionInfo([GO_TO_DOCK | {"status": "aborted"}]))
    assert len(uploads) == 0
    assert "waiting" in panel.widget.ui.vehiclesSelectedLabel.text()

    panel.receive(_executionInfo([]))
    assert [list(u) for u in uploads] == [[panel.plan, {SAM}]]
    assert "waiting" not in panel.widget.ui.vehiclesSelectedLabel.text()


def test_free_server_starts_without_asking(panel):
    uploads = QSignalSpy(panel.widget.sendMissionPlanRequested)
    panel.receive(_executionInfo([GO_TO_DOCK | {"task-name": "gimbal-stop"}]))

    panel.widget.ui.uploadMissionPlanButton.click()

    assert [list(u) for u in uploads] == [[panel.plan, {SAM}]]


def test_abort_of_one_task_is_a_signal_task(qgis_app):
    mqtt = MqttService(None)
    client = _Client()
    mqtt._client = client
    taskUuid = uuid4()

    mqtt.onAbortTasksSignal({SAM: [taskUuid]})

    [(topic, data)] = client.published
    assert topic == f"{SAM}/exec/command"
    assert data["command"] == "signal-task"
    assert data["signal"] == "$abort"
    assert data["task-uuid"] == str(taskUuid)
