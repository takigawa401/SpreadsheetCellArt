import json

import httplib2
from googleapiclient.discovery import build

from spreadsheet_cell_art.batching import encoded_size
from spreadsheet_cell_art.requests import color_request
from spreadsheet_cell_art.sheets_api import SheetsAPI


class RecordingHttp:
    def __init__(self):
        self.calls = []

    def request(self, uri, method="GET", body=None, headers=None, **kwargs):
        self.calls.append((uri, method, body))
        return httplib2.Response({"status": "200"}), b"{}"


def test_official_client_serialization_matches_size_and_request_contract():
    http = RecordingHttp()
    service = build("sheets", "v4", http=http, static_discovery=True, cache_discovery=False)
    api = SheetsAPI(service, min_interval=0)
    body = color_request(123, [[(17, 83, 255)]], 10, 20)
    api.batch_update("file123", body)
    uri, method, serialized = http.calls[0]
    assert method == "POST"
    assert "/v4/spreadsheets/file123:batchUpdate" in uri
    assert len(serialized.encode("utf-8")) == encoded_size(body)
    assert json.loads(serialized) == body
