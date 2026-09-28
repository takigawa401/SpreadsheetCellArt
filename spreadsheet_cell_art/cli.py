"""日本語CLI。事前検証とdry-runの後でのみGoogleへ接続する。"""

import argparse
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .config import DEFAULT_CELL_SIZE, Settings
from .errors import ArtError
from .imaging import load_render
from .preview import save_preview
from .render_data import RenderData
from .runner import plan_batches, run
from .state import StateError, StateStore, fingerprint, locked


def make_api(*args, **kwargs):
    from .auth import make_api as factory

    return factory(*args, **kwargs)


def parser():
    result = argparse.ArgumentParser(
        description=f"JPEG画像をGoogle Sheetsの{DEFAULT_CELL_SIZE}pxセル背景色で描きます。"
    )
    result.add_argument("--image", type=Path, help="入力JPG/JPEG")
    result.add_argument("--columns", type=int, help="横セル数（既定100）")
    result.add_argument("--title", help="スプレッドシートのタイトル")
    result.add_argument("--max-cells", type=int, help="総セル数上限（既定100000）")
    result.add_argument("--batch-bytes", type=int, help="送信本文のバイト数上限（既定1000000）")
    result.add_argument("--output-dir", type=Path, help="ローカル出力先")
    result.add_argument("--config", type=Path, help="TOML設定ファイル")
    result.add_argument("--dry-run", action="store_true", help="Googleに接続せずPNG/JSONを保存")
    result.add_argument("--resume", type=Path, help="再開するstate.json")
    result.add_argument("--adopt-spreadsheet", help="作成結果不明の確認済みファイルID")
    result.add_argument("--credentials", type=Path, help="デスクトップ用OAuthクライアントJSON")
    result.add_argument("--token", type=Path, help="トークン保存先")
    result.add_argument("--reauth", action="store_true", help="保存トークンを使わず再認証")
    result.add_argument(
        "--probe", action="store_true", help=f"組み込み2×2画像で{DEFAULT_CELL_SIZE}pxと色を実測"
    )
    result.add_argument("--verify-colors", action="store_true", help="完了後に全セルの色を再取得")
    return result


def read_config(path):
    if path is None:
        return {}
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    allowed = {
        "art": {"columns", "title", "max_cells", "batch_bytes"},
        "google": {"credentials", "token"},
        "output": {"directory"},
    }
    for section, values in config.items():
        if section not in allowed or not isinstance(values, dict) or set(values) - allowed[section]:
            raise ValueError(
                "設定ファイルに未対応の項目があります。config.example.tomlを確認してください。"
            )
    return config


def prepare(args):
    if args.dry_run and args.resume:
        raise ValueError("--dry-run と --resume は同時に指定できません。")
    if args.adopt_spreadsheet and not args.resume:
        raise ValueError("--adopt-spreadsheet には --resume が必要です。")
    config = read_config(args.config)
    previous = StateStore.load(args.resume, recover=False) if args.resume else None
    if previous and previous.data["phase"] in {"prepared", "create_failed"}:
        raise StateError(
            "再開できる作成済みファイルがありません。原因を解消し、"
            "新しい出力先で通常実行してください。--resume では新規作成しません。"
        )
    probe = args.probe or (
        previous is not None and previous.data["plan"]["image"].get("kind") == "probe"
    )
    if probe and args.image:
        raise ValueError("検証用の --probe と --image は同時に指定できません。")
    image_path = args.image or (Path(previous.data["input_path"]) if previous else None)
    if image_path is None and not probe:
        raise ValueError("--image、--probe、--resume のいずれかを指定してください。")
    name = f"{DEFAULT_CELL_SIZE}px検証" if probe else image_path.stem
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    values = (
        previous.data["plan"]["settings"].copy()
        if previous
        else Settings(columns=2 if probe else 100, title=f"{name}-{stamp}").as_dict()
    )
    legacy_size = previous is not None and "cell_size" not in values
    if legacy_size:
        values["cell_size"] = 1
    values.update(config.get("art", {}))
    for key in ("columns", "title", "max_cells", "batch_bytes"):
        value = getattr(args, key)
        if value is not None:
            values[key] = value
    settings = Settings(**values)
    settings.validate()
    if probe:
        if settings.columns != 2 or settings.max_cells < 4:
            raise ValueError("--probe は2列×2行です。列数2・セル数上限4以上を指定してください。")
        render = RenderData(
            2,
            2,
            (((255, 0, 0), (0, 255, 0)), ((0, 0, 255), (255, 255, 255))),
            {"kind": "probe", "original_size": [2, 2], "oriented_size": [2, 2]},
            settings.as_dict(),
        )
    else:
        render = load_render(image_path, settings)
    if legacy_size:
        # 旧計画のハッシュを保ち、再開時に既存作品のサイズを変えない。
        render.settings.pop("cell_size")
    if previous and fingerprint(render.as_dict()) != previous.data["plan_sha256"]:
        raise StateError("画像・設定・描画データが前回と一致しません。")
    output = args.output_dir or config.get("output", {}).get("directory")
    if previous:
        if output and Path(output).resolve() != args.resume.parent.resolve():
            raise ValueError("再開時はstate.jsonと同じ出力先を指定してください。")
        output = args.resume.parent
    output = Path(output) if output else Path("outputs") / f"{stamp}-{uuid4().hex[:8]}"
    if not previous and (output / "state.json").exists():
        raise StateError("出力先に状態ファイルが既にあります。--resume で再開してください。")
    # 認証・ファイル作成前に、1セル分でも送信容量に収まるか確認する。
    batch_count = len(plan_batches(render))
    return render, image_path, output, previous, config, probe, batch_count


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        render, image_path, output, previous, config, probe, batch_count = prepare(args)
        width, height = render.image["original_size"]
        print(f"元画像: {width:,}×{height:,} px / EXIF補正後: {render.image['oriented_size']}")
        print(
            f"描画: {render.columns:,}列×{render.rows:,}行 = {render.columns * render.rows:,}セル"
        )
        size = render.cell_size
        print(f"セル指定: {size}×{size} px / グリッド線: 表示 / 着色の送信回数: {batch_count}")
        with locked(output):
            if previous:
                store = StateStore.load(args.resume, render.as_dict())
            else:
                if (output / "state.json").exists():
                    raise StateError("状態ファイルが既にあります。--resume で再開してください。")
                store = None
            save_preview(render, output)
            if args.dry_run:
                print(f"dry-run完了: {output.resolve()}（Google接続なし・{size}px表示は未検証）")
                return 0
            google = config.get("google", {})
            api = make_api(
                args.credentials or Path(google.get("credentials", ".secrets/client_secret.json")),
                args.token or Path(google.get("token", ".secrets/token.json")),
                reauth=args.reauth,
                max_bytes=render.settings["batch_bytes"],
            )
            if store is None:
                store = StateStore.create(
                    output / "state.json",
                    render.as_dict(),
                    str(image_path) if image_path else "<built-in-probe>",
                )
            url = run(render, store, api, adopt_spreadsheet=args.adopt_spreadsheet)
            if probe or args.verify_colors:
                from .verification import verify_result

                verify_result(render, store, api, output / "verification.json")
                print(
                    f"API再取得で全行・全列{size}px、グリッド線表示、RGB色を確認しました。"
                    "ブラウザ表示は未検証です。"
                )
            print(f"完了: {url}")
        return 0
    except (ArtError, StateError, ValueError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    except OSError:
        print(
            "エラー: ファイルの読み書きに失敗しました。パス・権限・空き容量を確認してください。",
            file=sys.stderr,
        )
        return 1
    except (KeyError, TypeError):
        print("エラー: 設定または保存データの形式が不正です。", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            "中断しました。state.jsonがある場合は --resume で状態を確認してください。",
            file=sys.stderr,
        )
        return 130
