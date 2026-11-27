"""The officer refuses a TST with an empty seq or conc, so the dock never sends one."""

from types import SimpleNamespace

import pytest

import src.ui.widgets.MissionControlDockWidget as dock_module
from src.domain.missionplan import GroupKind, MissionPlan, TaskGroup
from src.domain.tasks import SmarcWaitTask
from src.ui.widgets.MissionControlDockWidget import MissionControlDockWidget


@pytest.fixture
def upload(qgis_app, monkeypatch: pytest.MonkeyPatch):
    """Call the dock's upload slot with a given plan; return (plans sent, warnings)."""
    sent: list[MissionPlan] = []
    warnings: list[str] = []
    bar = SimpleNamespace(pushWarning=lambda title, text: warnings.append(text))
    monkeypatch.setattr(dock_module, "iface", SimpleNamespace(messageBar=lambda: bar))
    dock = MissionControlDockWidget.__new__(MissionControlDockWidget)
    dock._fleetContext = SimpleNamespace(
        mqtt=SimpleNamespace(onPublishMissionPlan=lambda plan, receivers: sent.append(plan)))

    def call(plan: MissionPlan | None) -> tuple[list[MissionPlan], list[str]]:
        doc = None if plan is None else SimpleNamespace(plan=plan)
        dock._missionContext = SimpleNamespace(activeDocument=lambda: doc)
        dock.onUploadMissionPlanRequested({"waraps/unit/air/real/sam"})
        return sent, warnings

    return call


def _wait() -> SmarcWaitTask:
    return SmarcWaitTask.__new__(SmarcWaitTask)


def test_nothing_is_sent_without_an_open_mission(upload) -> None:
    sent, warnings = upload(None)
    assert sent == []
    assert "No mission plan is open" in warnings[-1]


def test_a_mission_with_no_tasks_is_not_sent(upload) -> None:
    sent, warnings = upload(MissionPlan(name="seq", description="empty"))
    assert sent == []
    assert "has no tasks" in warnings[-1]


def test_an_empty_group_deep_in_the_tree_stops_the_upload_and_is_named(upload) -> None:
    inner = TaskGroup(kind=GroupKind.CONC, description="survey legs")
    outer = TaskGroup(kind=GroupKind.SEQ, description="leg 1", children=[_wait(), inner])
    sent, warnings = upload(MissionPlan(name="seq", description="tree", tasks=[_wait(), outer]))
    assert sent == []
    assert '"survey legs"' in warnings[-1]


def test_a_mission_with_tasks_and_full_groups_is_sent_once(upload) -> None:
    group = TaskGroup(kind=GroupKind.SEQ, description="leg 1", children=[_wait()])
    plan = MissionPlan(name="seq", description="tree", tasks=[_wait(), group])
    sent, _ = upload(plan)
    assert sent == [plan]
