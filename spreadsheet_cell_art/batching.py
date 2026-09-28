"""公式クライアントと同じJSON直列化で通信本文を約1MB以下に分割。"""

import json

from .requests import color_request


def encoded_size(body: dict) -> int:
    return len(json.dumps(body).encode("utf-8"))


def split_batches(pixels, sheet_id: int, max_bytes: int = 1_000_000):
    pending = None
    pending_bytes = 0
    for row_index, pixels_row in enumerate(pixels):
        single = color_request(sheet_id, [pixels_row], row_index, 0)
        single_bytes = encoded_size(single)
        row_data = single["requests"][0]["updateCells"]["rows"][0]
        row_bytes = encoded_size(row_data)
        if pending is not None and pending_bytes + 2 + row_bytes <= max_bytes:
            pending["requests"][0]["updateCells"]["rows"].append(row_data)
            pending_bytes += 2 + row_bytes  # 行間の「, 」も含める。
            continue
        if pending is not None:
            yield pending
            pending = None
        if single_bytes <= max_bytes:
            pending, pending_bytes = single, single_bytes
            continue
        # 1行だけで超過する場合、列方向に収まる最大範囲を二分探索する。
        column = 0
        while column < len(pixels_row):
            low, high = 1, len(pixels_row) - column
            best = None
            while low <= high:
                count = (low + high) // 2
                candidate = color_request(
                    sheet_id,
                    [pixels_row[column : column + count]],
                    row_index,
                    column,
                )
                if encoded_size(candidate) <= max_bytes:
                    best = candidate
                    low = count + 1
                else:
                    high = count - 1
            if best is None:
                raise ValueError("送信容量の上限が小さすぎて1セルの要求も入りません。")
            yield best
            column += len(best["requests"][0]["updateCells"]["rows"][0]["values"])
    if pending is not None:
        yield pending


def cell_count(body: dict) -> int:
    return sum(len(row["values"]) for row in body["requests"][0]["updateCells"]["rows"])
