import json

import pytest
from PIL import Image

from spreadsheet_cell_art.batching import encoded_size, split_batches
from spreadsheet_cell_art.preview import save_preview
from spreadsheet_cell_art.render_data import RenderData


def test_preview_and_json_share_exact_rgb_data(tmp_path):
    pixels = (((255, 0, 0), (0, 255, 0)), ((0, 0, 255), (27, 99, 231)))
    render = RenderData(2, 2, pixels, {}, {})
    save_preview(render, tmp_path)
    with Image.open(tmp_path / "preview.png") as preview:
        assert preview.size == (2, 2)
        for y, row in enumerate(pixels):
            for x, color in enumerate(row):
                assert preview.getpixel((x, y)) == color
    data = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert data == render.as_dict()


@pytest.mark.parametrize("budget", [600, 2000, 10000])
def test_byte_limited_batches_cover_every_cell_once_without_shift(budget):
    pixels = tuple(tuple((r * 17, c * 13, (r + c) * 7) for c in range(13)) for r in range(9))
    batches = list(split_batches(pixels, 987654321, budget))
    assert len(batches) > 1
    found = {}
    for body in batches:
        assert encoded_size(body) == len(json.dumps(body).encode("utf-8"))
        assert encoded_size(body) <= budget
        update = body["requests"][0]["updateCells"]
        start = update["start"]
        for dy, row in enumerate(update["rows"]):
            for dx, cell in enumerate(row["values"]):
                position = (start["rowIndex"] + dy, start["columnIndex"] + dx)
                assert position not in found
                found[position] = cell["userEnteredFormat"]["backgroundColorStyle"]["rgbColor"]
    assert len(found) == 9 * 13
    for (r, c), rgb in found.items():
        assert [rgb[k] for k in ("red", "green", "blue")] == [v / 255 for v in pixels[r][c]]


def test_too_small_budget_rejected_before_sending():
    with pytest.raises(ValueError, match="1セル"):
        list(split_batches([[(1, 2, 3)]], 0, 20))


def test_batches_use_multiple_rows_when_possible():
    bodies = list(split_batches([[(0, 0, 0)]] * 3, 0, 1000))
    assert len(bodies) == 1
    assert len(bodies[0]["requests"][0]["updateCells"]["rows"]) == 3
