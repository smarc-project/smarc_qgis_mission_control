from pathlib import Path

from qgis.PyQt.QtCore import Qt, pyqtBoundSignal

from src.domain.missionplan import GroupKind, MissionPlan, TaskGroup
from src.domain.tasks import MovePathTask
from src.mission.MissionContext import MissionContext
from src.mission.MissionDocument import MissionDocument
from src.ui.widgets.MissionPlanWidget import MissionPlanWidget


def _open(plan: MissionPlan, tmp_path: Path) -> tuple[MissionPlanWidget, MissionDocument]:
    """Open the plan the way the dock does: from a file, through the context."""
    import json

    path = tmp_path / "mission.json"
    path.write_text(json.dumps(plan.toJson()))
    context = MissionContext()
    widget = MissionPlanWidget(context)
    context.activeMissionChanged.connect(widget.onActiveMissionChanged)
    context.loadMissionFromFile(path)
    context.changeActiveMission(plan.uuid)
    return widget, context.activeDocument()


def test_the_task_list_shows_the_plan(qgis_app, tmp_path: Path):
    plan = MissionPlan(
        name=GroupKind.SEQ.value,
        description="out and back",
        tasks=[MovePathTask(description="go out")],
    )
    widget, doc = _open(plan, tmp_path)
    widget.show()
    qgis_app.processEvents()

    model = widget.taskListModel
    root = model.index(0, 0)
    assert model.data(root) == "out and back"
    assert model.data(model.index(0, 1)) == "Sequence"
    child = model.index(0, 0, root)
    assert model.data(child) == "go out"
    assert model.data(model.index(0, 1, root)) == "move-path"
    assert widget.ui.taskList.isVisible()
    assert widget.ui.missionPlanTimeout.text() == "300.0"
    assert not widget.ui.taskListSidebar.isVisible()
    assert not widget.ui.taskEditorStack.isVisible()
    widget.ui.taskList.setCurrentIndex(child)
    qgis_app.processEvents()
    assert widget.ui.taskEditorStack.isVisible()
    # A dock about 520 px tall holds the panel. The tallest hidden editor must not count.
    assert widget.minimumSizeHint().height() <= 520


def test_a_concurrent_group_nests_under_the_sequence(qgis_app, tmp_path: Path):
    together = TaskGroup(
        kind=GroupKind.CONC,
        description="together",
        children=[
            MovePathTask(description="left"),
            MovePathTask(description="right"),
        ],
    )
    plan = MissionPlan(
        name=GroupKind.SEQ.value,
        description="out and back",
        tasks=[MovePathTask(description="go out"), together],
    )
    sent = plan.toJson()
    assert sent["name"] == "seq"
    assert sent["children"][1]["name"] == "conc"
    assert [child["description"] for child in sent["children"][1]["children"]] == ["left", "right"]
    loaded = MissionPlan.fromJson(sent)
    assert loaded.leaves()[1].description == "left"

    widget, doc = _open(loaded, tmp_path)
    widget.resize(480, 520)
    widget.ui.taskList.expandAll()
    widget.show()
    qgis_app.processEvents()

    root = widget.taskListModel.index(0, 0)
    assert widget.taskListModel.rowCount(root) == 2
    group = widget.taskListModel.index(1, 0, root)
    assert widget.taskListModel.data(group) == "together"
    assert widget.taskListModel.rowCount(group) == 2

    widget.ui.taskList.setCurrentIndex(group)
    qgis_app.processEvents()
    current = widget.taskListModel.node(widget.ui.taskList.currentIndex())
    assert current.description == "together"
    selected = widget.ui.taskList.selectionModel().selectedRows()
    labels = sorted(widget.taskListModel.data(index) for index in selected)
    assert labels == ["left", "right", "together"]
    assert widget.ui.missionPlanTimeout.text() == "300.0"

    doc.startEditing()
    widget.onAddGroup(GroupKind.SEQ)
    qgis_app.processEvents()
    root = widget.taskListModel.index(0, 0)
    group = widget.taskListModel.index(1, 0, root)
    assert widget.taskListModel.rowCount(group) == 3
    assert widget.taskListModel.data(widget.taskListModel.index(2, 1, group)) == "Sequence"


def test_a_map_click_task_lands_in_the_selected_group(qgis_app, tmp_path: Path):
    from uuid import uuid4

    from qgis.core import QgsPointXY

    from src.domain.tasks import MoveToTask, PendingWaypointTask
    from src.domain.waypoints import GeoPoint

    group = TaskGroup(kind=GroupKind.CONC, description="together")
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[group])
    doc = MissionDocument(plan, tmp_path / "mission.json")
    pending = PendingWaypointTask(
        taskCls=MoveToTask,
        fieldName="waypoint",
        waypointCls=GeoPoint,
        description="there",
        taskUuid=uuid4(),
        waypointUuid=uuid4(),
        parentUuid=group.uuid,
    )
    doc.addPendingWaypointTask(pending, QgsPointXY(18.07, 59.35))
    assert doc.plan.tasks[0].children[0].description == "there"
    assert doc.plan.toJson()["children"][0]["children"][0]["name"] == "move-to"


def _move_to(description: str):
    from uuid import uuid4

    from src.domain.tasks import MoveToTask
    from src.domain.waypoints import GeoPoint

    return MoveToTask(description=description, uuid=uuid4(),
                      waypoint=GeoPoint(latitude=59.35, longitude=18.07, uuid=uuid4()))


def test_deleting_the_only_waypoint_of_a_grouped_task_deletes_the_task(qgis_app, tmp_path: Path):
    task = _move_to("there")
    group = TaskGroup(kind=GroupKind.CONC, description="together", children=[task])
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[group])
    doc = MissionDocument(plan, tmp_path / "mission.json")
    doc.startEditing()

    doc.deleteWaypoint(task.waypoint.uuid)

    assert group.children == []
    assert doc.layerBridge.featureIdForWaypointUuid(task.waypoint.uuid) is None


def _track_segments(doc: MissionDocument) -> int:
    return doc.layerBridge.tracks._layer.featureCount()


def test_deleting_a_group_takes_its_waypoints_and_undo_brings_them_back(qgis_app, tmp_path: Path):
    left, right = _move_to("left"), _move_to("right")
    group = TaskGroup(kind=GroupKind.CONC, description="together", children=[left, right])
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out",
                       tasks=[_move_to("before"), group, _move_to("after")])
    doc = MissionDocument(plan, tmp_path / "mission.json")
    doc.startEditing()
    stack = doc.layerBridge.waypointLayer.undoStack()
    assert _track_segments(doc) == 3

    doc.deleteGroup(group)
    assert [task.description for task in plan.tasks] == ["before", "after"]
    assert _track_segments(doc) == 1
    for task in (left, right):
        assert doc.index.taskByUuid(task.uuid) is None
        assert doc.layerBridge.featureIdForWaypointUuid(task.waypoint.uuid) is None

    stack.undo()
    assert plan.tasks[1] is group and group.children == [left, right]
    assert _track_segments(doc) == 3
    for task in (left, right):
        assert doc.index.taskByUuid(task.uuid) is task
        assert doc.layerBridge.featureIdForWaypointUuid(task.waypoint.uuid) is not None

    stack.redo()
    assert _track_segments(doc) == 1


def test_the_rail_and_the_menu_only_work_in_edit_mode(qgis_app, tmp_path: Path):
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[])
    widget, doc = _open(plan, tmp_path)
    widget.show()
    qgis_app.processEvents()
    assert not widget.ui.taskListSidebar.isVisible()
    assert not widget.ui.missionPlanDescription.isEnabled()

    doc.startEditing()
    qgis_app.processEvents()
    assert widget.ui.taskListSidebar.isVisible()
    assert widget.ui.missionPlanDescription.isEnabled()


def test_renaming_a_task_in_the_tree_keeps_the_tree_open(qgis_app, tmp_path: Path):
    together = TaskGroup(kind=GroupKind.CONC, description="together",
                         children=[MovePathTask(description="left")])
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[together])
    widget, doc = _open(plan, tmp_path)
    widget.show()
    doc.startEditing()
    qgis_app.processEvents()
    model = widget.taskListModel
    group = model.index(0, 0, model.index(0, 0))
    left = model.index(0, 0, group)
    widget.ui.taskList.setCurrentIndex(left)

    assert not model.flags(group) & Qt.ItemIsEditable
    assert model.setData(left, "port")
    qgis_app.processEvents()

    assert doc.plan.tasks[0].children[0].description == "port"
    assert widget.ui.taskList.isExpanded(group)
    assert model.node(widget.ui.taskList.currentIndex()).description == "port"


def _record(signal: pyqtBoundSignal) -> list[tuple]:
    emitted: list[tuple] = []
    signal.connect(lambda *args: emitted.append(args))
    return emitted


def test_a_group_has_its_own_signals_and_task_signals_carry_only_tasks(qgis_app, tmp_path: Path):
    left, right = _move_to("left"), _move_to("right")
    together = TaskGroup(kind=GroupKind.CONC, description="together", children=[left, right])
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[together])
    doc = MissionDocument(plan, tmp_path / "mission.json")
    doc.startEditing()
    stack = doc.layerBridge.waypointLayer.undoStack()
    tasksAdded = _record(doc.taskAdded)
    tasksDeleted = _record(doc.taskDeleted)
    groupsAdded = _record(doc.groupAdded)
    groupsDeleted = _record(doc.groupDeleted)

    added = doc.addGroup(GroupKind.SEQ)
    assert groupsAdded == [(added.uuid, 1)]
    assert tasksAdded == []

    doc.deleteGroup(together)
    assert groupsDeleted == [(together.uuid, 0)]
    assert [uuid for uuid, _ in tasksDeleted] == [right.uuid, left.uuid]

    # Undo re-adds the children through the task path, then the group itself.
    stack.undo()
    assert groupsAdded[-1] == (together.uuid, 0)
    assert [uuid for uuid, _ in tasksAdded] == [left.uuid, right.uuid]


def test_the_tree_selects_a_new_group_and_drops_a_deleted_one(qgis_app, tmp_path: Path):
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[_move_to("first")])
    widget, doc = _open(plan, tmp_path)
    widget.show()
    doc.startEditing()
    qgis_app.processEvents()
    model = widget.taskListModel
    # The plan row is not a group, so the new group lands at the top level.
    widget.ui.taskList.setCurrentIndex(model.index(0, 0))

    widget.onAddGroup(GroupKind.CONC)
    qgis_app.processEvents()
    added = doc.plan.tasks[1]
    assert isinstance(added, TaskGroup)
    assert model.node(widget.ui.taskList.currentIndex()) is added
    assert model.rowCount(model.index(0, 0)) == 2

    doc.deleteGroup(added)
    qgis_app.processEvents()
    assert model.rowCount(model.index(0, 0)) == 1
    assert model.node(model.index(0, 0, model.index(0, 0))).description == "first"


def test_the_plan_finds_any_node_but_only_groups_as_groups(qgis_app):
    left = _move_to("left")
    together = TaskGroup(kind=GroupKind.CONC, description="together", children=[left])
    plan = MissionPlan(name=GroupKind.SEQ.value, description="out", tasks=[together])

    assert plan.findNode(left.uuid) is left
    assert plan.findNode(together.uuid) is together
    assert plan.findGroup(together.uuid) is together
    # A task is not a group, and None names the root.
    assert plan.findGroup(left.uuid) is None
    assert plan.findGroup(None) is None
