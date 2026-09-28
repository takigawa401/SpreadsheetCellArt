import hashlib

import pytest
from PIL import Image

from spreadsheet_cell_art.config import Settings
from spreadsheet_cell_art.imaging import grid_size, load_render, resize_rgb


def test_grid_size_preserves_ratio_and_rounds_half_up():
    assert grid_size(4000, 3000, 100) == (100, 75)
    assert grid_size(4, 1, 2) == (2, 1)
    assert grid_size(10, 3, 5) == (5, 2)


def test_box_averages_rgb_without_palette():
    image = Image.new("RGB", (2, 2))
    image.putdata([(20, 40, 60), (40, 60, 80), (60, 80, 100), (80, 100, 120)])
    assert resize_rgb(image, 1).getpixel((0, 0)) == (50, 70, 90)
    assert resize_rgb(image, 2).tobytes() == image.tobytes()


def test_jpeg_exif_and_fingerprint(tmp_path):
    path = tmp_path / "portrait.JPG"
    image = Image.new("RGB", (4, 2), (33, 75, 129))
    exif = image.getexif()
    exif[274] = 6
    image.save(path, exif=exif)
    render = load_render(path, Settings(columns=2, title="test"))
    assert (render.columns, render.rows) == (2, 4)
    assert render.image["original_size"] == [4, 2]
    assert render.image["oriented_size"] == [2, 4]
    assert render.image["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(render.pixels) == 4


@pytest.mark.parametrize("mode", ["L", "CMYK"])
def test_jpeg_converted_to_rgb(tmp_path, mode):
    path = tmp_path / "input.jpeg"
    Image.new(mode, (2, 2)).save(path)
    render = load_render(path, Settings(columns=2))
    assert all(len(rgb) == 3 for row in render.pixels for rgb in row)


@pytest.mark.parametrize(
    "field,value",
    [
        ("columns", 0),
        ("columns", -1),
        ("columns", True),
        ("columns", 1.5),
        ("max_cells", 0),
        ("title", " "),
        ("batch_bytes", 0),
        ("columns", 18279),
    ],
)
def test_invalid_settings(field, value):
    with pytest.raises(ValueError):
        Settings(**{field: value}).validate()


def test_cell_limit_and_upscaling_rejected(tmp_path):
    path = tmp_path / "input.jpg"
    Image.new("RGB", (20, 20)).save(path)
    with pytest.raises(ValueError, match="上限"):
        load_render(path, Settings(columns=20, max_cells=399))
    with pytest.raises(ValueError, match="横幅"):
        load_render(path, Settings(columns=21))


def test_invalid_missing_and_disguised_files(tmp_path):
    path = tmp_path / "image.jpg"
    with pytest.raises(ValueError, match="見つかり"):
        load_render(path, Settings(columns=2))
    Image.new("RGB", (2, 2)).save(path, format="PNG")
    with pytest.raises(ValueError, match="JPEG"):
        load_render(path, Settings(columns=2))
    path.write_bytes(b"not an image")
    with pytest.raises(ValueError, match="読み込"):
        load_render(path, Settings(columns=2))
