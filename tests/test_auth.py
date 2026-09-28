import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from spreadsheet_cell_art import auth
from spreadsheet_cell_art.errors import ArtError


@pytest.fixture
def auth_setup(tmp_path, monkeypatch):
    client = tmp_path / "client_secret.json"
    client.write_text(json.dumps({"installed": {"client_id": "test"}}))
    token = tmp_path / "token.json"
    credentials = Mock(valid=True, expired=False, refresh_token="secret")
    credentials.has_scopes.return_value = True
    credentials.granted_scopes = None
    credentials.to_json.return_value = '{"token": "secret"}'
    libraries = SimpleNamespace(Credentials=Mock(), InstalledAppFlow=Mock(), Request=Mock())
    libraries.Credentials.from_authorized_user_file.return_value = credentials
    flow = libraries.InstalledAppFlow.from_client_secrets_file.return_value
    flow.run_local_server.return_value = credentials
    monkeypatch.setattr(auth, "_libraries", lambda: libraries)
    return client, token, credentials, libraries


def test_valid_token_does_not_open_browser(auth_setup):
    client, token, credentials, libraries = auth_setup
    token.write_text("{}")
    assert auth.authenticate(client, token) is credentials
    libraries.InstalledAppFlow.from_client_secrets_file.assert_not_called()


def test_expired_token_is_refreshed_and_saved(auth_setup):
    client, token, credentials, libraries = auth_setup
    token.write_text("{}")
    credentials.valid, credentials.expired = False, True

    def refreshed(_):
        credentials.valid = True

    credentials.refresh.side_effect = refreshed
    auth.authenticate(client, token)
    credentials.refresh.assert_called_once()
    assert json.loads(token.read_text())["token"] == "secret"


def test_refresh_failure_guides_reauth_without_secret(auth_setup):
    client, token, credentials, libraries = auth_setup
    token.write_text("{}")
    credentials.valid, credentials.expired = False, True
    credentials.refresh.side_effect = RuntimeError("SECRET-TOKEN")
    with pytest.raises(ArtError, match="reauth") as caught:
        auth.authenticate(client, token)
    assert "SECRET-TOKEN" not in str(caught.value)


def test_first_auth_uses_drive_file_and_loopback(auth_setup):
    client, token, credentials, libraries = auth_setup
    auth.authenticate(client, token)
    call = libraries.InstalledAppFlow.from_client_secrets_file.call_args
    assert call.args == (str(client), ["https://www.googleapis.com/auth/drive.file"])
    flow = libraries.InstalledAppFlow.from_client_secrets_file.return_value
    assert flow.run_local_server.call_args.kwargs["port"] == 0
    assert token.exists()


def test_reauth_ignores_existing_invalid_token(auth_setup):
    client, token, credentials, libraries = auth_setup
    token.write_text("invalid")
    auth.authenticate(client, token, reauth=True)
    libraries.Credentials.from_authorized_user_file.assert_not_called()


def test_missing_client_is_actionable(auth_setup):
    client, token, credentials, libraries = auth_setup
    client.unlink()
    with pytest.raises(ArtError, match="デスクトップ"):
        auth.authenticate(client, token)
