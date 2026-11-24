from pathlib import Path

from src.domain.missionplan import MissionPlan
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
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "go out"
    assert model.data(model.index(0, 1)) == "move-path"
    assert widget.ui.taskList.isVisible()
