import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtTest import QSignalSpy, QTest
from qgis.PyQt.QtWidgets import QApplication, QMessageBox

import src.ui.widgets.MissionControlDockWidget as dock_module
from src.context.FleetState import INACTIVE_CHECK_INTERVAL, FleetState
from src.context.MqttService import MqttService
from src.domain.missionplan import GroupKind, MissionPlan, TaskGroup
from src.domain.tasks import LoiterTask, MoveToTask
from src.domain.waypoints import GeoPoint
from src.ui.widgets.FleetControlWidget import (
    ABORT_MISSION_BUTTON_CLICKS_REQUIRED,
    EMERGENCY_BUTTON_CLICKS_REQUIRED,
    FleetControlWidget,
)
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

    def commands(self, command: str) -> list[dict]:
        return [data for _, data in self.published if data.get("command") == command]


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


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


def _reply(comUuid: str, response: str) -> bytes:
    # The officer's ExecReply, as waraps_officer.commands.dumps writes it.
    return json.dumps({
        "agent-uuid": "officer", "com-uuid": comUuid,
        "response": response, "response-to": comUuid,
    }).encode()


GO_TO_DOCK = {
    "task-uuid": str(RUNNING),
    "task-name": "move-to",
    "status": "running",
    "description": "Go to dock",
}


@pytest.fixture
def panel(qgis_app, monkeypatch: pytest.MonkeyPatch):
    mqtt = MqttService(None)
    client = _Client()
    mqtt._client = client
    clock = _Clock()
    state = FleetState(mqtt, None, clock=clock)
    state.setInactiveTimeout(60)
    plan = MissionPlan(name="seq", description="Survey", tasks=[
        MoveToTask(description="Go to start", waypoint=GeoPoint(latitude=58.25, longitude=11.45)),
        LoiterTask(description="Wait"),
    ])
    warnings: list[str] = []
    bar = SimpleNamespace(pushWarning=lambda title, text: warnings.append(text))
    monkeypatch.setattr(dock_module, "iface", SimpleNamespace(messageBar=lambda: bar))

    widget = FleetControlWidget(state, _MapManager())
    # The dock's own slots, wired as MissionControlDockWidget.setup wires them, so a click
    # takes the one path: plan checks, busy check, plan checks again, publish.
    dock = MissionControlDockWidget.__new__(MissionControlDockWidget)
    dock._missionContext = SimpleNamespace(activeDocument=lambda: SimpleNamespace(plan=plan))
    dock._fleetContext = SimpleNamespace(mqtt=mqtt)
    dock.ui = SimpleNamespace(tabFleetControl=widget)
    # The dock is not a constructed QObject, so PyQt will not connect to its slots directly.
    widget.uploadMissionPlanRequested.connect(
        lambda vehicleTopics: dock.onUploadMissionPlanRequested(vehicleTopics)
    )
    widget.sendMissionPlanRequested.connect(
        lambda sentPlan, vehicleTopics: dock.onSendMissionPlanRequested(sentPlan, vehicleTopics)
    )
    widget.abortTasksRequested.connect(mqtt.onAbortTasksSignal)
    mqtt.commandRefused.connect(
        lambda vehicleTopic, command, reason: dock.onCommandRefused(vehicleTopic, command, reason)
    )

    def receive(subtopic: str, payload: bytes) -> None:
        message = SimpleNamespace(topic=f"{SAM}/{subtopic}", payload=payload)
        mqtt.onMqttMessage(None, None, message)

    receive("tst_execution_info", _executionInfo([GO_TO_DOCK]))
    widget.selectAll()
    return SimpleNamespace(
        widget=widget, mqtt=mqtt, plan=plan, receive=receive, client=client,
        clock=clock, warnings=warnings,
    )


def _answerBusyDialog(buttonText: str, seen: list[str], meanwhile=lambda: None) -> None:
    """Click buttonText on the busy-server box once it is open, noting what it said.

    meanwhile runs while the box is open, before the click.
    """
    def answer() -> None:
        box = QApplication.activeModalWidget()
        assert isinstance(box, QMessageBox)
        seen.append(f"{box.text()}\n{box.informativeText()}")
        meanwhile()
        [button] = [b for b in box.buttons() if b.text().replace("&", "") == buttonText]
        button.click()
    QTimer.singleShot(0, answer)


def _override(panel) -> None:
    seen: list[str] = []
    _answerBusyDialog("Override", seen)
    panel.widget.ui.uploadMissionPlanButton.click()
    assert len(seen) == 1


def test_start_on_busy_server_is_refused_with_the_reason(panel):
    seen: list[str] = []

    _answerBusyDialog("Cancel", seen)
    panel.widget.ui.uploadMissionPlanButton.click()

    [text] = seen
    assert "sam1" in text and "move-to" in text and "Go to dock" in text
    # The status adds nothing while it is "running", the word the line already says.
    assert "(running)" not in text
    assert panel.client.published == []
    # Refused, not greyed out: the operator can always ask again.
    assert panel.widget.ui.uploadMissionPlanButton.isEnabled()


def test_override_confirms_aborts_then_starts_when_the_server_is_free(panel):
    _override(panel)

    [abort] = panel.client.commands("signal-task")
    assert (abort["signal"], abort["task-uuid"]) == ("$abort", str(RUNNING))
    # The officer still lists the task while its server cancels it.
    panel.receive("tst_execution_info", _executionInfo([GO_TO_DOCK | {"status": "aborted"}]))
    assert panel.client.commands("start-tst") == []
    assert "sam1: plan waits for move-to to stop" in panel.widget.ui.vehiclesSelectedLabel.text()

    panel.receive("tst_execution_info", _executionInfo([]))
    [start] = panel.client.commands("start-tst")
    assert start["tst"]["tst-uuid"] == str(panel.plan.uuid)
    assert "waits" not in panel.widget.ui.vehiclesSelectedLabel.text()


def test_free_server_starts_without_asking(panel):
    panel.receive("tst_execution_info", _executionInfo([GO_TO_DOCK | {"task-name": "gimbal-stop"}]))

    panel.widget.ui.uploadMissionPlanButton.click()

    assert len(panel.client.commands("start-tst")) == 1


def test_a_plan_emptied_while_waiting_is_checked_again_and_not_sent(panel):
    _override(panel)
    panel.plan.tasks.append(TaskGroup(kind=GroupKind.SEQ, description="leg 2"))

    panel.receive("tst_execution_info", _executionInfo([]))

    assert panel.client.commands("start-tst") == []
    assert '"leg 2"' in panel.warnings[-1]


def test_a_waiting_plan_is_dropped_when_the_vehicle_goes_silent(panel):
    _override(panel)

    panel.clock.now += 70
    QTest.qWait(INACTIVE_CHECK_INTERVAL + 200)

    assert "sam1: plan dropped, vehicle went silent" in panel.widget.ui.vehiclesSelectedLabel.text()
    # Heard again with the server free: the dropped plan must not start on its own.
    panel.receive("tst_execution_info", _executionInfo([]))
    assert panel.client.commands("start-tst") == []


def test_an_officer_refusal_shows_its_reason_naming_the_vehicle(panel):
    panel.receive("tst_execution_info", _executionInfo([]))
    panel.widget.ui.uploadMissionPlanButton.click()
    panel.widget.ui.uploadMissionPlanButton.click()
    refused, accepted = panel.client.commands("start-tst")

    # A reply to some other operator's command is not ours to show.
    panel.receive("tst/response", _reply(str(uuid4()), "task already executing on a mission"))
    panel.receive("tst/response", _reply(accepted["com-uuid"], "accepted"))
    assert panel.warnings == []

    panel.receive("tst/response", _reply(refused["com-uuid"], "task already executing on a mission"))

    [warning] = panel.warnings
    assert warning == "sam1 refused the mission plan: task already executing on a mission"


@pytest.mark.parametrize("button, clicks", [
    ("abortMissionButton", ABORT_MISSION_BUTTON_CLICKS_REQUIRED),
    ("emergencyButton", EMERGENCY_BUTTON_CLICKS_REQUIRED),
])
def test_stopping_the_vehicle_drops_its_waiting_plan(panel, button: str, clicks: int):
    _override(panel)

    for _ in range(clicks):
        getattr(panel.widget.ui, button).click()
    # The officer drains tasks-executing after a stop; the plan must not start then.
    panel.receive("tst_execution_info", _executionInfo([]))

    assert panel.client.commands("start-tst") == []
    assert "sam1: plan dropped" in panel.widget.ui.vehiclesSelectedLabel.text()


def test_upload_again_and_cancel_takes_the_waiting_plan_back(panel):
    _override(panel)
    seen: list[str] = []

    _answerBusyDialog("Cancel", seen)
    panel.widget.ui.uploadMissionPlanButton.click()
    panel.receive("tst_execution_info", _executionInfo([]))

    assert "already waiting" in seen[0]
    assert panel.client.commands("start-tst") == []


def test_a_task_that_ends_while_the_box_is_open_is_not_aborted_and_the_plan_starts(panel):
    seen: list[str] = []
    # No later execution info changes, so no later update would start the plan.
    _answerBusyDialog(
        "Override",
        seen,
        meanwhile=lambda: panel.receive("tst_execution_info", _executionInfo([])),
    )
    panel.widget.ui.uploadMissionPlanButton.click()

    assert panel.client.commands("signal-task") == []
    assert len(panel.client.commands("start-tst")) == 1


def test_a_server_busy_again_after_the_abort_drops_the_plan(panel):
    _override(panel)
    # The officer refuses by server, not by task: any task on move-to blocks the plan.
    other = GO_TO_DOCK | {"task-uuid": str(uuid4()), "description": "Someone else's"}

    panel.receive("tst_execution_info", _executionInfo([other]))

    assert panel.client.commands("start-tst") == []
    assert "sam1: plan dropped, move-to busy again" in panel.widget.ui.vehiclesSelectedLabel.text()


def test_only_plan_and_task_signal_refusals_are_awaited_and_a_silent_vehicle_forgets_them(panel):
    refusals = QSignalSpy(panel.mqtt.commandRefused)
    panel.mqtt.publishAbortMissionSignal(SAM)
    [abortMission] = panel.client.commands("signal-unit")
    panel.receive("tst/response", _reply(abortMission["com-uuid"], "invalid signal"))
    assert len(refusals) == 0

    panel.receive("tst_execution_info", _executionInfo([]))
    panel.widget.ui.uploadMissionPlanButton.click()
    [start] = panel.client.commands("start-tst")
    panel.clock.now += 70
    QTest.qWait(INACTIVE_CHECK_INTERVAL + 200)
    panel.receive("tst/response", _reply(start["com-uuid"], "task not available"))

    assert len(refusals) == 0


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
