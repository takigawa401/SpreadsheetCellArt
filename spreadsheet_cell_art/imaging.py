"""JPEGの検証・識別と平均色の生成。Miro版のEXIF/BOX処理を基に分離。"""

import hashlib
import warnings
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import SHEETS_CELL_LIMIT, Settings
from .render_data import RenderData


def grid_size(width: int, height: int, columns: int) -> tuple[int, int]:
    if any(type(value) is not int or value <= 0 for value in (width, height, columns)):
        raise ValueError("画像寸法と列数は1以上の整数が必要です。")
    if columns > width:
        raise ValueError("列数はEXIF補正後の画像の横幅以下にしてください。")
    return columns, max(1, (2 * height * columns + width) // (2 * width))


def resize_rgb(image: Image.Image, columns: int) -> Image.Image:
    oriented = ImageOps.exif_transpose(image)
    return oriented.convert("RGB").resize(
        grid_size(*oriented.size, columns),
        Image.Resampling.BOX,
    )


def load_render(path: Path, settings: Settings) -> RenderData:
    settings.validate()
    path = Path(path)
    if not path.is_file():
        raise ValueError("入力画像が見つかりません。--image を確認してください。")
    if path.suffix.lower() not in (".jpg", ".jpeg"):
        raise ValueError("入力には .jpg または .jpeg を指定してください。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with path.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
                byte_size = source.tell()
                source.seek(0)
                with Image.open(source) as image:
                    if image.format != "JPEG":
                        raise ValueError("入力ファイルの実体がJPEGではありません。")
                    original_size = image.size
                    orientation = image.getexif().get(274, 1)
                    oriented_size = image.size[::-1] if orientation in (5, 6, 7, 8) else image.size
                    columns, rows = grid_size(*oriented_size, settings.columns)
                    limit = min(settings.max_cells, SHEETS_CELL_LIMIT)
                    if columns * rows > limit:
                        raise ValueError(
                            f"総セル数 {columns * rows:,} は上限 {limit:,} を超えます。"
                        )
                    mosaic = resize_rgb(image, settings.columns)
                    pixels = tuple(
                        tuple(mosaic.getpixel((x, y)) for x in range(columns)) for y in range(rows)
                    )
        return RenderData(
            columns,
            rows,
            pixels,
            {
                "sha256": digest,
                "bytes": byte_size,
                "original_size": list(original_size),
                "oriented_size": list(oriented_size),
            },
            settings.as_dict(),
        )
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ValueError(
            "JPEG画像を読み込めません。破損・権限・画像サイズを確認してください。"
        ) from error
