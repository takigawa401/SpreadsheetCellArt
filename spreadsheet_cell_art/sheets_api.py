"""Google公式クライアントの薄い境界。作成は自動再試行しない。"""

import json
import random
import time

from .errors import ArtError, CreationRejected, CreationUnknown

RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}


def status_of(error):
    return getattr(getattr(error, "resp", None), "status", None)


def error_info(error) -> tuple[set[str], str | None]:
    """既知の理由判定に必要な情報だけを読む。生の本文・URL・metadataは表示しない。"""
    try:
        payload = json.loads(error.content)
    except (AttributeError, TypeError, ValueError):
        return set(), None
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return set(), None
    reasons = set()
    service = None
    for key in ("errors", "details"):
        entries = payload["error"].get(key, [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            reason = entry.get("reason")
            if isinstance(reason, str):
                reasons.add(reason)
            metadata = entry.get("metadata", {})
            if isinstance(metadata, dict):
                candidate = metadata.get("service")
                if isinstance(candidate, str) and candidate in {
                    "sheets.googleapis.com",
                    "drive.googleapis.com",
                }:
                    service = candidate
    return reasons, service


def retryable(error) -> bool:
    status = status_of(error)
    if status in RETRY_STATUSES or isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return True
    if type(error).__name__ in {"TransportError", "ServerNotFoundError"}:
        return True
    if status == 403:
        reasons, _ = error_info(error)
        return bool(reasons & RATE_REASONS)
    return False


def safe_error(error) -> str:
    status = status_of(error)
    if status == 401 or type(error).__name__ == "RefreshError":
        return "認証情報が無効です。--reauth で再認証してください。"
    if status == 403:
        reasons, service = error_info(error)
        if reasons & {"accessNotConfigured", "SERVICE_DISABLED"}:
            api_name = {
                "sheets.googleapis.com": "Google Sheets API",
                "drive.googleapis.com": "Google Drive API",
            }.get(service, "呼び出し先のGoogle API")
            return (
                f"{api_name}が無効、または有効化が未反映です (HTTP 403)。"
                "OAuthクライアントを作成したプロジェクトのAPI画面で「有効にする」を押し、"
                "反映後に再実行してください。"
            )
        if reasons & {"insufficientPermissions", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}:
            return (
                "アクセストークンの権限が不足しています (HTTP 403)。"
                "--reauth で再認証し、drive.file のアクセス許可を確認してください。"
            )
        if "storageQuotaExceeded" in reasons:
            return "Google Driveの保存容量が不足しています (HTTP 403)。空き容量を確認してください。"
        return (
            "権限がありません。Sheets APIの有効化・drive.fileの同意・"
            "使用アカウントを確認してください。"
        )
    if status == 404:
        return "対象ファイルが見つかりません。削除・ファイルID・アカウントを確認してください。"
    if status == 400:
        return (
            "Google APIが入力を拒否しました。"
            "行列数・タイトル・セルサイズ設定などを確認してください。"
        )
    if status is not None:
        return f"Google APIとの通信に失敗しました (HTTP {status})。"
    return "Googleとの通信に失敗しました。接続と認証を確認してください。"


class SheetsAPI:
    def __init__(
        self,
        service,
        *,
        sleep=time.sleep,
        jitter=random.random,
        clock=time.monotonic,
        max_retries=5,
        min_interval=1.1,
        max_bytes=1_000_000,
    ):
        self.service = service
        self.sleep, self.jitter, self.clock = sleep, jitter, clock
        self.max_retries, self.min_interval, self.max_bytes = max_retries, min_interval, max_bytes
        self.last_request = None

    def _execute(self, request, *, creation=False):
        for attempt in range(self.max_retries + 1):
            if self.last_request is not None and self.min_interval:
                self.sleep(max(0, self.min_interval - (self.clock() - self.last_request)))
            self.last_request = self.clock()
            try:
                return request.execute(num_retries=0)
            except Exception as error:
                status = status_of(error)
                if creation:
                    if status is not None and 400 <= status < 500 and status != 408:
                        raise CreationRejected(safe_error(error)) from None
                    raise CreationUnknown(
                        "作成要求の結果が不明です。自動再送は行いません。"
                    ) from None
                if not retryable(error):
                    raise ArtError(safe_error(error)) from None
                if attempt == self.max_retries:
                    raise ArtError(
                        "通信の再試行上限に達しました。--resume で再開できます。"
                    ) from None
                self.sleep(min(2**attempt + self.jitter(), 32))

    def create(self, body):
        request = self.service.spreadsheets().create(
            body=body,
            fields="spreadsheetId,properties(title),sheets(properties)",
        )
        return self._execute(request, creation=True)

    def batch_update(self, spreadsheet_id, body):
        request = self.service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body)
        # googleapiclient自身が生成した実送信本文を再確認する。
        raw = request.body.encode("utf-8") if isinstance(request.body, str) else request.body
        if len(raw) > self.max_bytes:
            raise ArtError("直列化後の送信容量が上限を超えました。着色は送信していません。")
        return self._execute(request)

    def get(self, spreadsheet_id):
        return self._execute(
            self.service.spreadsheets().get(
                spreadsheetId=spreadsheet_id,
                fields=(
                    "spreadsheetId,properties(title),sheets(properties,"
                    "data(startRow,startColumn,rowMetadata(pixelSize),columnMetadata(pixelSize)))"
                ),
            )
        )

    def get_colors(self, spreadsheet_id):
        return self._execute(
            self.service.spreadsheets().get(
                spreadsheetId=spreadsheet_id,
                fields=(
                    "sheets(data(startRow,startColumn,"
                    "rowData(values(userEnteredFormat(backgroundColorStyle)))))"
                ),
            )
        )
