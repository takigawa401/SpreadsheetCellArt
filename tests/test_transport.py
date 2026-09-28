import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from spreadsheet_cell_art.errors import ArtError, CreationRejected, CreationUnknown
from spreadsheet_cell_art.sheets_api import SheetsAPI, safe_error


class HTTPFailure(Exception):
    def __init__(self, status, reason=""):
        self.resp = {"status": str(status)}
        self.resp = SimpleNamespace(status=status)
        self.content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()


def api_with_errors(errors, **kwargs):
    request = Mock()
    request.execute.side_effect = [*errors, {"ok": True}]
    request.body = "{}"
    service = Mock()
    service.spreadsheets.return_value.batchUpdate.return_value = request
    service.spreadsheets.return_value.create.return_value = request
    waits = []
    api = SheetsAPI(service, sleep=waits.append, jitter=lambda: 0, min_interval=0, **kwargs)
    return api, request, waits


def test_retry_429_and_503_with_backoff():
    api, request, waits = api_with_errors([HTTPFailure(429), HTTPFailure(503)])
    assert api.batch_update("id", {}) == {"ok": True}
    assert waits == [1, 2]
    assert request.execute.call_count == 3
    assert all(call.kwargs == {"num_retries": 0} for call in request.execute.call_args_list)


def test_retry_has_finite_limit():
    api, request, waits = api_with_errors([HTTPFailure(429)] * 6, max_retries=2)
    with pytest.raises(ArtError, match="再試行"):
        api.batch_update("id", {})
    assert request.execute.call_count == 3
    assert waits == [1, 2]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_errors_do_not_retry_or_expose_content(status):
    api, request, waits = api_with_errors([HTTPFailure(status, "SECRET")])
    with pytest.raises(ArtError) as caught:
        api.batch_update("id", {})
    assert "SECRET" not in str(caught.value)
    assert request.execute.call_count == 1
    assert waits == []


def test_403_rate_limit_is_distinct_from_permission_denied():
    api, request, waits = api_with_errors([HTTPFailure(403, "userRateLimitExceeded")])
    api.batch_update("id", {})
    assert waits == [1]


@pytest.mark.parametrize("error", [TimeoutError("secret"), HTTPFailure(503)])
def test_creation_never_automatically_retries_ambiguous_errors(error):
    api, request, waits = api_with_errors([error])
    with pytest.raises(CreationUnknown):
        api.create({})
    assert request.execute.call_count == 1
    assert waits == []


def test_definite_creation_rejection_is_reported():
    api, request, waits = api_with_errors([HTTPFailure(400)])
    with pytest.raises(CreationRejected):
        api.create({})
    assert request.execute.call_count == 1


def test_actual_serialized_request_is_checked_before_network():
    api, request, waits = api_with_errors([], max_bytes=500)
    request.body = "あ" * 200
    with pytest.raises(ArtError, match="容量"):
        api.batch_update("id", {})
    request.execute.assert_not_called()


@pytest.mark.parametrize("modern", [False, True])
def test_disabled_api_is_distinct_from_missing_scope_and_hides_raw_content(modern):
    error = HTTPFailure(403, "accessNotConfigured")
    if modern:
        error.content = json.dumps(
            {
                "error": {
                    "message": "SECRET-MESSAGE",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "SERVICE_DISABLED",
                            "metadata": {
                                "service": "sheets.googleapis.com",
                                "consumer": "SECRET-PROJECT",
                            },
                        }
                    ],
                }
            }
        ).encode()
    message = safe_error(error)
    assert "無効" in message
    assert "有効にする" in message
    assert "SECRET" not in message
    if modern:
        assert "Google Sheets API" in message
    api, request, waits = api_with_errors([error])
    with pytest.raises(CreationRejected, match="無効"):
        api.create({})
    assert request.execute.call_count == 1


@pytest.mark.parametrize("modern", [False, True])
def test_missing_scope_explicitly_guides_reauthentication(modern):
    error = HTTPFailure(403, "insufficientPermissions")
    if modern:
        error.content = json.dumps(
            {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
                        }
                    ]
                }
            }
        ).encode()
    assert "--reauth" in safe_error(error)
    assert "drive.file" in safe_error(error)


def test_storage_quota_failure_is_actionable():
    assert "空き容量" in safe_error(HTTPFailure(403, "storageQuotaExceeded"))


@pytest.mark.parametrize(
    "content", [b"SECRET", b"[]", b'{"error": []}', b'{"error":{"errors":[null],"details":[null]}}']
)
def test_malformed_error_content_falls_back_without_disclosure(content):
    error = HTTPFailure(403)
    error.content = content
    assert "SECRET" not in safe_error(error)
    api, request, waits = api_with_errors([error])
    with pytest.raises(ArtError):
        api.batch_update("id", {})
    assert request.execute.call_count == 1
