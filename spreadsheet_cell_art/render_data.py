"""プレビューとAPI描画が共通で使う、RGB描画データ。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderData:
    columns: int
    rows: int
    pixels: tuple
    image: dict
    settings: dict

    @property
    def cell_size(self) -> int:
        # 旧版の保存データはサイズ項目を持たず、1px固定だった。
        return self.settings.get("cell_size", 1)

    def as_dict(self) -> dict:
        return {
            "schema_version": 1,
            "conversion": "exif-rgb-box-v1",
            "columns": self.columns,
            "rows": self.rows,
            "pixels": [[list(rgb) for rgb in row] for row in self.pixels],
            "image": self.image,
            "settings": self.settings,
        }
