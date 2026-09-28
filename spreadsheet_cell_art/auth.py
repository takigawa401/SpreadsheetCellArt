"""デスクトップOAuth。dry-runの経路ではこのモジュールを呼ばない。"""

import json
from pathlib import Path
from types import SimpleNamespace

from .errors import ArtError
from .state import atomic_json

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _libraries():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    return SimpleNamespace(
        Credentials=Credentials, InstalledAppFlow=InstalledAppFlow, Request=Request
    )


def authenticate(client_path: Path, token_path: Path, *, reauth=False):
    libraries = _libraries()
    client_path, token_path = Path(client_path), Path(token_path)
    credentials = None
    if token_path.exists() and not reauth:
        try:
            credentials = libraries.Credentials.from_authorized_user_file(str(token_path), SCOPES)
            if not credentials.has_scopes(SCOPES):
                raise ValueError
            if not credentials.valid:
                if credentials.expired and credentials.refresh_token:
                    credentials.refresh(libraries.Request())
                else:
                    raise ValueError
        except Exception:
            raise ArtError(
                "保存トークンの読み込み・更新に失敗しました。--reauth で再認証してください。"
            ) from None
    if credentials is None:
        try:
            definition = json.loads(client_path.read_text(encoding="utf-8"))
            if "installed" not in definition:
                raise ValueError
        except (OSError, ValueError, TypeError):
            raise ArtError(
                "デスクトップ用OAuthクライアントのJSONが必要です。Google Cloudで作成し、"
                ".secrets/client_secret.json に保存するか --credentials で指定してください。"
            ) from None
        try:
            flow = libraries.InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
            credentials = flow.run_local_server(
                port=0,
                open_browser=True,
                timeout_seconds=180,
                authorization_prompt_message="認証用ブラウザを開きました。本人のアカウントで許可してください。",
                success_message="認証が完了しました。このタブを閉じてください。",
                access_type="offline",
                prompt="consent",
            )
        except Exception:
            raise ArtError(
                "ブラウザ認証を完了できませんでした。設定を確認し、再実行してください。"
            ) from None
    if not credentials.valid or not credentials.has_scopes(SCOPES):
        raise ArtError("必要な権限を確認できません。--reauth で drive.file を許可してください。")
    if credentials.granted_scopes is not None and not set(SCOPES) <= set(
        credentials.granted_scopes
    ):
        raise ArtError("drive.file が許可されていません。--reauth で再認証してください。")
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(token_path, json.loads(credentials.to_json()))
    except (OSError, ValueError):
        raise ArtError(
            "トークンを保存できません。保存先の権限・空き容量を確認してください。"
        ) from None
    return credentials


def make_api(client_path, token_path, *, reauth=False, max_bytes=1_000_000):
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build

    from .sheets_api import SheetsAPI

    credentials = authenticate(client_path, token_path, reauth=reauth)
    transport = AuthorizedHttp(credentials, http=httplib2.Http(timeout=200))
    service = build("sheets", "v4", http=transport, cache_discovery=False, static_discovery=True)
    return SheetsAPI(service, max_bytes=max_bytes)
