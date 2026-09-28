"""通信しない、Sheets API v4リクエストの組み立て。"""

from .config import DEFAULT_CELL_SIZE


def create_request(title: str, sheet_title: str, rows: int, columns: int) -> dict:
    return {
        "properties": {"title": title},
        "sheets": [
            {
                "properties": {
                    "title": sheet_title,
                    "gridProperties": {"rowCount": rows, "columnCount": columns},
                }
            }
        ],
    }


def size_request(
    sheet_id: int, rows: int, columns: int, pixel_size: int = DEFAULT_CELL_SIZE
) -> dict:
    return {
        "requests": [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": dimension,
                        "startIndex": 0,
                        "endIndex": count,
                    },
                    "properties": {"pixelSize": pixel_size},
                    "fields": "pixelSize",
                }
            }
            for dimension, count in (("ROWS", rows), ("COLUMNS", columns))
        ]
    }


def gridlines_request(sheet_id: int) -> dict:
    return {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"hideGridlines": False}},
                    "fields": "gridProperties.hideGridlines",
                }
            }
        ]
    }


def color_request(sheet_id: int, pixels, start_row: int, start_column: int) -> dict:
    return {
        "requests": [
            {
                "updateCells": {
                    "start": {
                        "sheetId": sheet_id,
                        "rowIndex": start_row,
                        "columnIndex": start_column,
                    },
                    "rows": [
                        {
                            "values": [
                                {
                                    "userEnteredFormat": {
                                        "backgroundColorStyle": {
                                            "rgbColor": {
                                                "red": red / 255,
                                                "green": green / 255,
                                                "blue": blue / 255,
                                            }
                                        }
                                    }
                                }
                                for red, green, blue in row
                            ]
                        }
                        for row in pixels
                    ],
                    "fields": "userEnteredFormat.backgroundColorStyle",
                }
            }
        ]
    }
