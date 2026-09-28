"""認証情報を含まない処理状態の原子的保存と同時実行防止。"""

import hashlib
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class StateError(RuntimeError):
    pass


def fingerprint(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".state-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class StateStore:
    def __init__(self, path: Path, data: dict):
        self.path, self.data = Path(path), data

    @classmethod
    def create(cls, path: Path, plan: dict, input_path: str):
        path = Path(path)
        if path.exists():
            raise StateError("状態ファイルが既にあります。--resume で再開してください。")
        run_id = uuid.uuid4().hex
        store = cls(
            path,
            {
                "schema_version": 1,
                "run_id": run_id,
                "sheet_title": f"Mosaic_{run_id[:12]}",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "plan": plan,
                "plan_sha256": fingerprint(plan),
                "input_path": str(Path(input_path).resolve()),
                "phase": "prepared",
                "spreadsheet_id": None,
                "sheet_id": None,
                "next_batch": 0,
                "completed_cells": 0,
            },
        )
        store.save()
        return store

    @classmethod
    def load(cls, path: Path, expected_plan: dict | None = None, *, recover=True):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if (
                data["schema_version"] != 1
                or fingerprint(data["plan"]) != data["plan_sha256"]
                or data["phase"]
                not in {
                    "prepared",
                    "creating",
                    "creation_unknown",
                    "created",
                    "sized",
                    "drawing",
                    "complete",
                    "create_failed",
                }
            ):
                raise ValueError
            if any(
                type(data[k]) is not int or data[k] < 0 for k in ("next_batch", "completed_cells")
            ):
                raise ValueError
            if expected_plan is not None and fingerprint(expected_plan) != data["plan_sha256"]:
                raise StateError("入力画像・設定・描画データが前回と一致しません。")
            if data["phase"] in {"created", "sized", "drawing", "complete"}:
                if not data["spreadsheet_id"] or type(data["sheet_id"]) is not int:
                    raise ValueError
            if not data["sheet_title"] or not data["run_id"] or not data["input_path"]:
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise StateError("状態ファイルの形式・整合性を確認できません。") from error
        store = cls(path, data)
        if recover and data["phase"] == "creating":
            store.update(phase="creation_unknown")
        return store

    def save(self) -> None:
        try:
            atomic_json(self.path, self.data)
        except OSError as error:
            raise StateError(
                "状態を保存できません。空き容量と書き込み権限を確認してください。"
            ) from error

    def update(self, **values) -> None:
        self.data.update(values)
        self.save()


@contextmanager
def locked(directory: Path):
    """プロセス終了時にOSが解放するロック。残ったファイル自体は問題ない。"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".run.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise StateError("同じ出力先で別の処理が実行中です。") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
