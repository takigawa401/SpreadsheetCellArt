from copy import deepcopy

import pytest

from spreadsheet_cell_art.config import Settings
from spreadsheet_cell_art.errors import ArtError, CreationRejected, CreationUnknown
from spreadsheet_cell_art.render_data import RenderData
from spreadsheet_cell_art.runner import run
from spreadsheet_cell_art.state import StateStore


class FakeSheets:
    def __init__(self, sheet_title):
        self.events = []
        self.document = {
            "spreadsheetId": "file123",
            "properties": {"title": "test"},
            "sheets": [
                {
                    "properties": {
                        "sheetId": 7,
                        "title": sheet_title,
                        "gridProperties": {"rowCount": 2, "columnCount": 2},
                    },
                    "data": [
                        {
                            "rowMetadata": [{"pixelSize": 20}] * 2,
                            "columnMetadata": [{"pixelSize": 20}] * 2,
                        }
                    ],
                }
            ],
        }
        self.fail_create = False
        self.fail_color_once = False
        self.fail_size = False

    def create(self, body):
        self.events.append(("create", deepcopy(body)))
        if self.fail_create:
            raise TimeoutError("lost response")
        return deepcopy(self.document)

    def batch_update(self, spreadsheet_id, body):
        self.events.append(("update", deepcopy(body)))
        if self.fail_size and "updateDimensionProperties" in body["requests"][0]:
            raise ArtError("20px was rejected")
        if self.fail_color_once and "updateCells" in body["requests"][0]:
            self.fail_color_once = False
            raise ArtError("connection failed")

    def get(self, spreadsheet_id):
        self.events.append(("get", spreadsheet_id))
        return deepcopy(self.document)


@pytest.fixture
def job(tmp_path):
    render = RenderData(
        2,
        2,
        (((255, 0, 0), (0, 255, 0)), ((0, 0, 255), (40, 50, 60))),
        {},
        Settings(columns=2, title="test", batch_bytes=600).as_dict(),
    )
    store = StateStore.create(tmp_path / "state.json", render.as_dict(), "input.jpg")
    return render, store, FakeSheets(store.data["sheet_title"])


def test_creation_size_readback_visible_gridlines_then_colors(job):
    render, store, api = job
    url = run(render, store, api)
    kinds = [
        kind if kind != "update" else next(iter(body["requests"][0])) for kind, body in api.events
    ]
    assert kinds[:4] == ["create", "updateDimensionProperties", "get", "updateSheetProperties"]
    assert all(kind == "updateCells" for kind in kinds[4:])
    assert store.data["phase"] == "complete"
    assert store.data["completed_cells"] == 4
    assert store.data["size_verification"]["verified"] is True
    assert store.data["size_verification"]["requested_pixel_size"] == 20
    assert [
        request["updateDimensionProperties"]["properties"]["pixelSize"]
        for request in api.events[1][1]["requests"]
    ] == [20, 20]
    assert url == "https://docs.google.com/spreadsheets/d/file123/edit#gid=7"


@pytest.mark.parametrize("value", [1, 2, None])
def test_size_correction_or_missing_metadata_stops_before_gridlines_and_colors(job, value):
    render, store, api = job
    api.document["sheets"][0]["data"][0]["rowMetadata"][1] = {"pixelSize": value}
    with pytest.raises(ArtError, match="20ピクセル"):
        run(render, store, api)
    assert len(api.events) == 3
    assert store.data["size_verification"]["verified"] is False


def test_rejected_size_never_draws(job):
    render, store, api = job
    api.fail_size = True
    with pytest.raises(ArtError):
        run(render, store, api)
    assert len(api.events) == 2
    assert store.data["phase"] == "created"


def test_failed_color_can_resume_without_create_or_resize(job):
    render, store, api = job
    api.fail_color_once = True
    with pytest.raises(ArtError):
        run(render, store, api)
    failed = api.events[-1][1]
    api.events.clear()
    run(render, StateStore.load(store.path, render.as_dict()), api)
    assert not any(kind == "create" for kind, _ in api.events)
    updates = [body for kind, body in api.events if kind == "update"]
    assert (
        updates[0]["requests"][0]["updateSheetProperties"]["properties"]["gridProperties"][
            "hideGridlines"
        ]
        is False
    )
    assert updates[1] == failed
    assert all("updateDimensionProperties" not in body["requests"][0] for body in updates)


def test_unknown_creation_never_retries_or_creates_on_resume(job):
    render, store, api = job
    api.fail_create = True
    with pytest.raises(CreationUnknown):
        run(render, store, api)
    assert store.data["phase"] == "creation_unknown"
    api.events.clear()
    with pytest.raises(CreationUnknown):
        run(render, StateStore.load(store.path), api)
    assert api.events == []


def test_explicit_adoption_matches_unique_sheet_name_then_initializes(job):
    render, store, api = job
    store.update(phase="creation_unknown")
    run(render, store, api, adopt_spreadsheet="file123")
    assert not any(kind == "create" for kind, _ in api.events)
    assert api.events[1][1]["requests"][0]["updateDimensionProperties"]


def test_adoption_of_unrelated_file_rejected(job):
    render, store, api = job
    store.update(phase="creation_unknown")
    api.document["sheets"][0]["properties"]["title"] = "unrelated"
    with pytest.raises(ArtError, match="一致"):
        run(render, store, api, adopt_spreadsheet="file123")
    assert [kind for kind, _ in api.events] == ["get"]


def test_completed_resume_does_not_redraw(job):
    render, store, api = job
    run(render, store, api)
    api.events.clear()
    run(render, StateStore.load(store.path), api)
    assert not any(kind == "create" for kind, _ in api.events)
    assert not any(
        kind == "update" and "updateCells" in body["requests"][0] for kind, body in api.events
    )


def test_incomplete_progress_cannot_be_marked_complete(job):
    render, store, api = job
    store.update(phase="complete", spreadsheet_id="file123", sheet_id=7)
    with pytest.raises(ArtError, match="進捗"):
        run(render, store, api)
    assert api.events == []


def test_resume_skips_confirmed_batches_after_later_failure(job):
    render, store, api = job
    original = api.batch_update
    colors = []

    def fail_second(spreadsheet_id, body):
        if "updateCells" in body["requests"][0]:
            colors.append(deepcopy(body))
            if len(colors) == 2:
                raise ArtError("lost response on second batch")
        return original(spreadsheet_id, body)

    api.batch_update = fail_second
    with pytest.raises(ArtError):
        run(render, store, api)
    assert store.data["next_batch"] == 1
    api.batch_update = original
    api.events.clear()
    run(render, StateStore.load(store.path), api)
    resumed_colors = [
        body
        for kind, body in api.events
        if kind == "update" and "updateCells" in body["requests"][0]
    ]
    assert resumed_colors[0] == colors[1]
    assert colors[0] not in resumed_colors


def test_creation_rejection_keeps_safe_reason_in_state(job):
    render, store, api = job

    def rejected(body):
        raise CreationRejected("Google Sheets APIが無効です。")

    api.create = rejected
    with pytest.raises(CreationRejected):
        run(render, store, api)
    restored = StateStore.load(store.path)
    assert restored.data["phase"] == "create_failed"
    assert restored.data["last_error"] == "Google Sheets APIが無効です。"
    assert restored.data["spreadsheet_id"] is None
