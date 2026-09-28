"""設定と、画像の展開・Google接続前に確認する制限。"""

from dataclasses import asdict, dataclass

SHEETS_CELL_LIMIT = 20_000_000
SUPPORTED_COLUMNS = 18_278
DEFAULT_CELL_SIZE = 20


@dataclass(frozen=True)
class Settings:
    columns: int = 100
    title: str = "セルアート"
    max_cells: int = 100_000
    batch_bytes: int = 1_000_000
    cell_size: int = DEFAULT_CELL_SIZE

    def validate(self) -> None:
        for name in ("columns", "max_cells", "batch_bytes", "cell_size"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} は1以上の整数を指定してください。")
        if self.columns > SUPPORTED_COLUMNS:
            raise ValueError(f"列数は初期版の上限 {SUPPORTED_COLUMNS:,} 列以下にしてください。")
        if self.batch_bytes > 1_000_000:
            raise ValueError("batch_bytes は1,000,000バイト以下にしてください。")
        if not isinstance(self.title, str) or not self.title.strip():
            raise ValueError("タイトルは空白以外の文字を含めてください。")

    def as_dict(self) -> dict:
        return asdict(self)
