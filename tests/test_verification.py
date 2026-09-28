import json
from unittest.mock import Mock

import pytest
from test_runner import FakeSheets

from spreadsheet_cell_art.errors import ArtError
from spreadsheet_cell_art.requests import color_request
from spreadsheet_cell_art.verification import verify_result


def verification_api(render, store):
    api = FakeSheets(store.data["sheet_title"])
    api.document["sheets"][0]["properties"]["gridProperties"]["hideGridlines"] = False
    data = color_request(7, render.pixels, 0, 0)["requests"][0]["updateCells"]
    api.get_colors = Mock(return_value={"sheets": [{"data": [{"rowData": data["rows"]}]}]})
    store.update(spreadsheet_id="file123", sheet_id=7, phase="complete")
    return api


def test_actual_colors_and_sizes_saved_with_browser_unverified(job, tmp_path):
    render, store, _ = job
    api = verification_api(render, store)
    path = tmp_path / "verification.json"
    verify_result(render, store, api, path)
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["api_verified"] is True
    assert report["checked_cells"] == 4
    assert report["dimensions"]["requested_pixel_size"] == 20
    assert report["browser_display"] == "未検証"


@pytest.mark.parametrize("problem", ["color", "size", "gridlines", "missing"])
def test_mismatch_saved_and_reported(job, tmp_path, problem):
    render, store, _ = job
    api = verification_api(render, store)
    if problem == "size":
        api.document["sheets"][0]["data"][0]["columnMetadata"] = [{"pixelSize": 2}] * 2
    elif problem == "gridlines":
        api.document["sheets"][0]["properties"]["gridProperties"]["hideGridlines"] = True
    elif problem == "missing":
        api.get_colors.return_value = {"sheets": [{"data": []}]}
    else:
        rgb = api.get_colors.return_value["sheets"][0]["data"][0]["rowData"][0]["values"][0][
            "userEnteredFormat"
        ]["backgroundColorStyle"]["rgbColor"]
        rgb["red"] = 0.5
    path = tmp_path / "verification.json"
    with pytest.raises(ArtError, match="検証"):
        verify_result(render, store, api, path)
    assert json.loads(path.read_text(encoding="utf-8"))["api_verified"] is False
