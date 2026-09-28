"""作成・全寸法の初期化・検証・グリッド線表示・着色・再開の順序管理。"""

from copy import deepcopy
from datetime import datetime, timezone
from time import monotonic

from .batching import cell_count, encoded_size, split_batches
from .config import DEFAULT_CELL_SIZE
from .errors import ArtError, CreationRejected, CreationUnknown
from .requests import create_request, gridlines_request, size_request
from .state import fingerprint

# 実際のsheetIdに置換しても本文サイズが増えないよう、最大桁数で分割する。
PLANNING_SHEET_ID = 2_147_483_647


def plan_batches(render):
    initial = size_request(PLANNING_SHEET_ID, render.rows, render.columns, render.cell_size)
    if encoded_size(initial) > render.settings["batch_bytes"]:
        raise ValueError("送信容量の上限が小さすぎて全行・全列のサイズ設定が入りません。")
    return list(split_batches(render.pixels, PLANNING_SHEET_ID, render.settings["batch_bytes"]))


def validate_structure(document: dict, render, store) -> int:
    try:
        sheets = document["sheets"]
        props = sheets[0]["properties"]
        grid = props["gridProperties"]
        if (
            len(sheets) != 1
            or props["title"] != store.data["sheet_title"]
            or document["properties"]["title"] != render.settings["title"]
            or grid["rowCount"] != render.rows
            or grid["columnCount"] != render.columns
            or type(props["sheetId"]) is not int
        ):
            raise ValueError
        if store.data["sheet_id"] is not None and props["sheetId"] != store.data["sheet_id"]:
            raise ValueError
        return props["sheetId"]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ArtError("対象ファイル・シート名・行列数が保存した計画と一致しません。") from error


def dimension_report(
    document: dict, rows: int, columns: int, pixel_size: int = DEFAULT_CELL_SIZE
) -> dict:
    row_sizes, column_sizes = [None] * rows, [None] * columns
    for block in document["sheets"][0].get("data", []):
        for key, start_key, sizes in (
            ("rowMetadata", "startRow", row_sizes),
            ("columnMetadata", "startColumn", column_sizes),
        ):
            start = block.get(start_key, 0)
            for offset, item in enumerate(block.get(key, [])):
                index = start + offset
                if 0 <= index < len(sizes):
                    sizes[index] = item.get("pixelSize")
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "requested_pixel_size": pixel_size,
        "row_pixel_sizes": row_sizes,
        "column_pixel_sizes": column_sizes,
        "verified": all(value == pixel_size for value in row_sizes + column_sizes),
        "browser_display": "未検証",
    }


def spreadsheet_url(store) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{store.data['spreadsheet_id']}/edit"
        f"#gid={store.data['sheet_id']}"
    )


def run(render, store, api, progress=print, adopt_spreadsheet: str | None = None) -> str:
    if fingerprint(render.as_dict()) != store.data["plan_sha256"]:
        raise ArtError("画像・設定が状態ファイルと一致しません。")
    batches = plan_batches(render)
    batches_hash = fingerprint({"batches": batches})
    previous_hash = store.data.get("batches_sha256")
    if previous_hash is not None and previous_hash != batches_hash:
        raise ArtError("分割結果が前回と一致しません。元のバージョンと設定で再開してください。")
    next_batch = store.data["next_batch"]
    if store.data["phase"] == "complete" and next_batch != len(batches):
        raise ArtError("完了状態と保存された進捗が一致しません。")
    if next_batch and store.data["phase"] not in {"drawing", "complete"}:
        raise ArtError("初期化段階と保存された進捗が一致しません。")
    if (
        next_batch > len(batches)
        or sum(cell_count(b) for b in batches[:next_batch]) != store.data["completed_cells"]
    ):
        raise ArtError("保存された進捗と送信範囲が一致しません。")
    if previous_hash is None:
        if next_batch:
            raise ArtError("分割結果の識別情報がありません。")
        store.update(batches_sha256=batches_hash)

    phase = store.data["phase"]
    if adopt_spreadsheet:
        if phase != "creation_unknown":
            raise ArtError("ファイルIDによる復旧は作成結果不明の場合だけ指定できます。")
        document = api.get(adopt_spreadsheet)
        sheet_id = validate_structure(document, render, store)
        if document.get("spreadsheetId") != adopt_spreadsheet:
            raise ArtError("取得したファイルIDが一致しません。")
        store.update(spreadsheet_id=adopt_spreadsheet, sheet_id=sheet_id, phase="created")
    elif phase in {"creating", "creation_unknown"}:
        raise CreationUnknown(
            "ファイル作成の結果が不明です。自動で再作成しません。マイドライブでタイトルと"
            f"シート名 {store.data['sheet_title']} を確認し、見つかったファイルIDを "
            "--adopt-spreadsheet に指定して --resume してください。"
        )
    elif phase == "create_failed":
        raise ArtError("前回の作成は拒否されました。原因を解消し、新しい出力先で実行してください。")
    elif phase == "prepared":
        store.update(phase="creating")
        try:
            document = api.create(
                create_request(
                    render.settings["title"],
                    store.data["sheet_title"],
                    render.rows,
                    render.columns,
                )
            )
            spreadsheet_id = document["spreadsheetId"]
            sheet_id = validate_structure(document, render, store)
            if not isinstance(spreadsheet_id, str) or not spreadsheet_id:
                raise ValueError
        except CreationRejected as error:
            store.update(phase="create_failed", last_error=str(error))
            raise
        except Exception:
            store.update(phase="creation_unknown")
            raise CreationUnknown(
                "作成応答を確認できませんでした。自動再作成は行いません。"
                "READMEの『作成結果が不明な場合』を確認してください。"
            ) from None
        store.update(spreadsheet_id=spreadsheet_id, sheet_id=sheet_id, phase="created")
        progress(f"作成先: {spreadsheet_url(store)}")

    spreadsheet_id, sheet_id = store.data["spreadsheet_id"], store.data["sheet_id"]
    if store.data["phase"] == "created":
        # この呼び出しが新規ファイル作成後の最初の更新であることを保つ。
        api.batch_update(
            spreadsheet_id, size_request(sheet_id, render.rows, render.columns, render.cell_size)
        )
        store.update(phase="sized")

    document = api.get(spreadsheet_id)
    validate_structure(document, render, store)
    report = dimension_report(document, render.rows, render.columns, render.cell_size)
    store.update(size_verification=report)
    if not report["verified"]:
        raise ArtError(
            f"全行・全列の{render.cell_size}ピクセル設定を確認できません。着色を停止しました。"
            "state.jsonのsize_verificationで取得値を確認してください。別サイズへは変更しません。"
        )
    api.batch_update(spreadsheet_id, gridlines_request(sheet_id))
    if store.data["phase"] == "complete":
        return spreadsheet_url(store)
    store.update(phase="drawing")
    started = monotonic()
    for index, planned in enumerate(batches):
        if index < next_batch:
            continue
        body = deepcopy(planned)
        body["requests"][0]["updateCells"]["start"]["sheetId"] = sheet_id
        api.batch_update(spreadsheet_id, body)
        completed = store.data["completed_cells"] + cell_count(body)
        store.update(next_batch=index + 1, completed_cells=completed)
        total = render.columns * render.rows
        progress(
            f"描画: {completed:,}/{total:,} セル ({completed / total:.1%}) "
            f"{monotonic() - started:.1f}秒"
        )
    store.update(phase="complete", drawing_seconds=round(monotonic() - started, 3))
    return spreadsheet_url(store)
