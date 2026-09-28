"""APIの再取得値を記録する。ブラウザでの表示確認とは区別する。"""

from datetime import datetime, timezone

from .errors import ArtError
from .runner import dimension_report, spreadsheet_url, validate_structure
from .state import atomic_json


def verify_result(render, store, api, path):
    document = api.get(store.data["spreadsheet_id"])
    validate_structure(document, render, store)
    dimensions = dimension_report(document, render.rows, render.columns, render.cell_size)
    grid = document["sheets"][0]["properties"]["gridProperties"]
    visible = not grid.get("hideGridlines", False)
    color_document = api.get_colors(store.data["spreadsheet_id"])
    actual = {}
    for sheet in color_document.get("sheets", []):
        for block in sheet.get("data", []):
            for dy, row in enumerate(block.get("rowData", [])):
                for dx, cell in enumerate(row.get("values", [])):
                    position = (block.get("startRow", 0) + dy, block.get("startColumn", 0) + dx)
                    actual[position] = (
                        cell.get("userEnteredFormat", {})
                        .get(
                            "backgroundColorStyle",
                            {},
                        )
                        .get("rgbColor")
                    )
    mismatches = []
    mismatch_count = 0
    for y, row in enumerate(render.pixels):
        for x, expected in enumerate(row):
            rgb = actual.get((y, x))
            matches = rgb is not None and all(
                abs(rgb.get(component, 0) - value / 255) <= 1 / 510
                for component, value in zip(("red", "green", "blue"), expected)
            )
            if not matches:
                mismatch_count += 1
                if len(mismatches) < 20:
                    mismatches.append(
                        {
                            "row": y,
                            "column": x,
                            "expected_rgb": list(expected),
                            "actual_api_rgb": rgb,
                        }
                    )
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "url": spreadsheet_url(store),
        "dimensions": dimensions,
        "gridlines_visible": visible,
        "checked_cells": render.columns * render.rows,
        "color_mismatch_count": mismatch_count,
        "mismatch_examples": mismatches,
        "api_verified": dimensions["verified"] and visible and mismatch_count == 0,
        "browser_display": "未検証",
    }
    atomic_json(path, report)
    store.update(final_verification=report)
    if not report["api_verified"]:
        raise ArtError("API再取得の検証で不一致がありました。verification.jsonを確認してください。")
    return report
