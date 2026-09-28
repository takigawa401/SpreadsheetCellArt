"""共通描画データのローカル出力。Googleの認証・通信は不要。"""

import json
from pathlib import Path

from PIL import Image

from .render_data import RenderData


def save_preview(render: RenderData, directory: Path) -> None:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (render.columns, render.rows))
    image.putdata([rgb for row in render.pixels for rgb in row])
    image.save(directory / "preview.png")
    (directory / "render.json").write_text(
        json.dumps(render.as_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
