from pathlib import Path

from src.domain.missionplan import MissionPlan, TaskGroup
from src.domain.tasks import MovePathTask
from src.mission.MissionContext import MissionContext
from src.mission.MissionDocument import MissionDocument
from src.ui.widgets.MissionPlanWidget import MissionPlanWidget


def test_the_task_list_shows_the_plan(qgis_app, tmp_path: Path):
    plan = MissionPlan(
        name="seq",
        description="out and back",
        tasks=[MovePathTask(description="go out")],
    )
    doc = MissionDocument(plan, tmp_path / "mission.json")
    widget = MissionPlanWidget(MissionContext())
    widget.onActiveMissionChanged(doc)
    widget.show()
    qgis_app.processEvents()

    model = widget.taskListModel
    root = model.index(0, 0)
    assert model.data(root) == "out and back"
    assert model.data(model.index(0, 1)) == "seq"
    child = model.index(0, 0, root)
    assert model.data(child) == "go out"
    assert model.data(model.index(0, 1, root)) == "move-path"
    assert widget.ui.taskList.isVisible()


def test_a_concurrent_group_nests_under_the_sequence(qgis_app, tmp_path: Path):
    together = TaskGroup(
        kind="conc",
        description="together",
        children=[
            MovePathTask(description="left"),
            MovePathTask(description="right"),
        ],
    )
    plan = MissionPlan(
        name="seq",
        description="out and back",
        tasks=[MovePathTask(description="go out"), together],
    )
    sent = plan.toJson()
    assert sent["name"] == "seq"
    assert sent["children"][1]["name"] == "conc"
    assert [child["description"] for child in sent["children"][1]["children"]] == ["left", "right"]
    loaded = MissionPlan.fromJson(sent)
    assert loaded.leaves()[1].description == "left"

    doc = MissionDocument(loaded, tmp_path / "mission.json")
    widget = MissionPlanWidget(MissionContext())
    widget.onActiveMissionChanged(doc)
    widget.resize(520, 320)
    widget.ui.taskList.expandAll()
    widget.show()
    qgis_app.processEvents()

    root = widget.taskListModel.index(0, 0)
    assert widget.taskListModel.rowCount(root) == 2
    group = widget.taskListModel.index(1, 0, root)
    assert widget.taskListModel.data(group) == "together"
    assert widget.taskListModel.rowCount(group) == 2
    widget.ui.taskList.grab().save("/tmp/mission_tree.png")

    widget.ui.taskList.setCurrentIndex(group)
    qgis_app.processEvents()
    current = widget.taskListModel.node(widget.ui.taskList.currentIndex())
    assert getattr(current, "description", None) == "together"
    selected = widget.ui.taskList.selectionModel().selectedRows()
    labels = sorted(widget.taskListModel.data(index) for index in selected)
    assert labels == ["left", "right", "together"]

    widget.onAddGroup("seq")
    qgis_app.processEvents()
    root = widget.taskListModel.index(0, 0)
    group = widget.taskListModel.index(1, 0, root)
    assert widget.taskListModel.rowCount(group) == 3
    assert widget.taskListModel.data(widget.taskListModel.index(2, 1, group)) == "seq"
