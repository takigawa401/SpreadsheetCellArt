import json
import sys
from unittest.mock import Mock

import pytest
from PIL import Image

from spreadsheet_cell_art import cli


def jpeg(tmp_path):
    path = tmp_path / "input.jpg"
    Image.new("RGB", (200, 150), (39, 71, 203)).save(path)
    return path


def test_dry_run_never_authenticates_or_imports_google(tmp_path, monkeypatch, capsys):
    factory = Mock(side_effect=AssertionError("Google must not be called"))
    monkeypatch.setattr(cli, "make_api", factory)
    before = {name for name in sys.modules if name.startswith("google")}
    output = tmp_path / "dry"
    assert cli.main(["--image", str(jpeg(tmp_path)), "--dry-run", "--output-dir", str(output)]) == 0
    factory.assert_not_called()
    assert before == {name for name in sys.modules if name.startswith("google")}
    assert not (output / "state.json").exists()
    data = json.loads((output / "render.json").read_text(encoding="utf-8"))
    assert (data["columns"], data["rows"]) == (100, 75)
    assert data["settings"]["cell_size"] == 20
    with Image.open(output / "preview.png") as preview:
        assert preview.size == (100, 75)
    stdout = capsys.readouterr().out
    assert "7,500" in stdout
    assert "セル指定: 20×20 px" in stdout


@pytest.mark.parametrize(
    "options",
    [
        ["--columns", "0"],
        ["--max-cells", "1"],
        ["--columns", "2", "--batch-bytes", "350"],
    ],
)
def test_invalid_input_stops_before_output_and_google(tmp_path, monkeypatch, options):
    factory = Mock()
    monkeypatch.setattr(cli, "make_api", factory)
    output = tmp_path / "invalid"
    assert cli.main(["--image", str(jpeg(tmp_path)), "--output-dir", str(output), *options]) == 1
    factory.assert_not_called()
    assert not output.exists()


def test_toml_settings_and_cli_override(tmp_path):
    config = tmp_path / "settings.toml"
    config.write_text('[art]\ncolumns=20\ntitle="example"\nmax_cells=1000\n')
    output = tmp_path / "configured"
    assert (
        cli.main(
            [
                "--image",
                str(jpeg(tmp_path)),
                "--config",
                str(config),
                "--columns",
                "10",
                "--dry-run",
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    data = json.loads((output / "render.json").read_text())
    assert data["columns"] == 10
    assert data["settings"]["title"] == "example"


def test_probe_dry_run_has_exact_four_colors(tmp_path):
    assert cli.main(["--probe", "--dry-run", "--output-dir", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert data["pixels"] == [[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [255, 255, 255]]]


def test_cli_resume_restores_settings_and_does_not_create(tmp_path, monkeypatch):
    class API:
        def __init__(self):
            self.created = 0
            self.doc = None

        def create(self, body):
            self.created += 1
            body["spreadsheetId"] = "file"
            props = body["sheets"][0]["properties"]
            props["sheetId"] = 0
            body["sheets"][0]["data"] = [
                {
                    "rowMetadata": [{"pixelSize": 20}] * props["gridProperties"]["rowCount"],
                    "columnMetadata": [{"pixelSize": 20}] * props["gridProperties"]["columnCount"],
                }
            ]
            self.doc = body
            return body

        def get(self, _):
            return self.doc

        def batch_update(self, *args):
            pass

    api = API()
    monkeypatch.setattr(cli, "make_api", lambda *args, **kwargs: api)
    path = jpeg(tmp_path)
    output = tmp_path / "live"
    assert cli.main(["--image", str(path), "--columns", "2", "--output-dir", str(output)]) == 0
    assert cli.main(["--resume", str(output / "state.json")]) == 0
    assert api.created == 1
    assert cli.main(["--resume", str(output / "state.json"), "--columns", "3"]) == 1
    assert api.created == 1


def test_resume_before_creation_does_not_create_file(tmp_path, monkeypatch):
    from spreadsheet_cell_art.config import Settings
    from spreadsheet_cell_art.imaging import load_render
    from spreadsheet_cell_art.state import StateStore

    image = jpeg(tmp_path)
    render = load_render(image, Settings(columns=2))
    path = tmp_path / "state.json"
    StateStore.create(path, render.as_dict(), str(image))
    factory = Mock(side_effect=AssertionError("must not authenticate"))
    monkeypatch.setattr(cli, "make_api", factory)
    assert cli.main(["--resume", str(path)]) == 1
    factory.assert_not_called()


@pytest.mark.parametrize("phase", ["created", "sized"])
def test_legacy_resume_preserves_one_pixel_without_new_file(tmp_path, monkeypatch, capsys, phase):
    from test_runner import FakeSheets

    from spreadsheet_cell_art.config import Settings
    from spreadsheet_cell_art.imaging import load_render
    from spreadsheet_cell_art.state import StateStore

    image = jpeg(tmp_path)
    plan = load_render(image, Settings(columns=2, title="test")).as_dict()
    plan["settings"].pop("cell_size", None)  # 旧版では寸法を保存していない。
    store = StateStore.create(tmp_path / "state.json", plan, str(image))
    store.update(phase=phase, spreadsheet_id="file123", sheet_id=7)
    api = FakeSheets(store.data["sheet_title"])
    api.document["sheets"][0]["data"] = [
        {"rowMetadata": [{"pixelSize": 1}] * 2, "columnMetadata": [{"pixelSize": 1}] * 2}
    ]
    monkeypatch.setattr(cli, "make_api", lambda *args, **kwargs: api)
    assert cli.main(["--resume", str(store.path)]) == 0
    assert "セル指定: 1×1 px" in capsys.readouterr().out
    assert not any(kind == "create" for kind, _ in api.events)
    sizes = [
        request["updateDimensionProperties"]["properties"]["pixelSize"]
        for kind, body in api.events
        if kind == "update"
        for request in body["requests"]
        if "updateDimensionProperties" in request
    ]
    assert sizes == ([1, 1] if phase == "created" else [])
    restored = StateStore.load(store.path)
    assert restored.data["plan"] == plan
    assert restored.data["size_verification"]["requested_pixel_size"] == 1
