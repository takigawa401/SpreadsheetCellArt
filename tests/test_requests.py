from spreadsheet_cell_art.requests import (
    color_request,
    create_request,
    gridlines_request,
    size_request,
)


def test_create_has_exactly_one_sheet_with_required_dimensions():
    body = create_request("日本語の作品", "Mosaic_test", 75, 100)
    assert body["properties"]["title"] == "日本語の作品"
    assert len(body["sheets"]) == 1
    assert body["sheets"][0]["properties"]["gridProperties"] == {
        "rowCount": 75,
        "columnCount": 100,
    }


def test_initial_size_request_only_updates_every_row_and_column_to_twenty():
    body = size_request(123, 75, 100)
    assert len(body["requests"]) == 2
    for request, dimension, end in zip(body["requests"], ["ROWS", "COLUMNS"], [75, 100]):
        update = request["updateDimensionProperties"]
        assert update == {
            "range": {"sheetId": 123, "dimension": dimension, "startIndex": 0, "endIndex": end},
            "properties": {"pixelSize": 20},
            "fields": "pixelSize",
        }


def test_gridlines_are_explicitly_visible():
    assert gridlines_request(7) == {
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": 7, "gridProperties": {"hideGridlines": False}},
                    "fields": "gridProperties.hideGridlines",
                }
            }
        ]
    }


def test_two_by_two_colors_are_positioned_from_top_left_without_values():
    pixels = [[(255, 0, 0), (0, 255, 0)], [(0, 0, 255), (128, 64, 32)]]
    body = color_request(7, pixels, 0, 0)
    update = body["requests"][0]["updateCells"]
    assert update["start"] == {"sheetId": 7, "rowIndex": 0, "columnIndex": 0}
    assert update["fields"] == "userEnteredFormat.backgroundColorStyle"
    for source_row, row in zip(pixels, update["rows"], strict=True):
        for rgb, cell in zip(source_row, row["values"], strict=True):
            assert cell == {
                "userEnteredFormat": {
                    "backgroundColorStyle": {
                        "rgbColor": {
                            "red": rgb[0] / 255,
                            "green": rgb[1] / 255,
                            "blue": rgb[2] / 255,
                        }
                    }
                }
            }
