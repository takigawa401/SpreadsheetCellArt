# SpreadsheetCellArt

ローカルのJPG/JPEGを縮小し、1ピクセルをGoogleスプレッドシートの1セルの背景色として描くPython CLIです。Google公式Pythonクライアントから **Sheets API v4を直接使用**します。

新規作品のセルは全行・全列 **20×20ピクセル固定**、**グリッド線は表示**します。画像の縮小後のRGB値を使用し、固定パレットへの減色はしません。作品ごとにマイドライブに新しいファイルを作成します。100列×75行なら、セルサイズ設定の合計は横2,000×縦1,500pxです（画面上の大きさは表示倍率などによって異なります）。

> 2026-09-28のご要望で、標準サイズを1pxから20pxへ変更しました。20px版はオフラインテスト済みで、ご本人からも期待どおりの動作を確認できたとの報告をいただきました。旧1px版の実測結果とは区別して [検証結果](docs/verification.md) に記録しています。初回は以下の小さな `--probe` から検証してください。

## 1. VS Codeでの環境構築

Python 3.11以上を使用します。ローカルで確認した環境はWindows / Python 3.11です。

1. VS Codeで本リポジトリのフォルダーを開きます。
2. Microsoftの「Python」「Python Debugger」拡張機能をインストールします。
3. PowerShellのターミナルで以下を実行します。

```powershell
cd C:\Python\SpreadsheetCellArt
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

最新の互換範囲で開発用依存を解決したい場合は `pip install -e ".[dev]"` でも導入できます。`requirements.lock` は今回動作確認した実行・開発依存の固定一覧です。

4. コマンドパレットの「Python: Select Interpreter」で `.venv\Scripts\python.exe` を選択します。
5. 「テスト」画面からpytestを実行できます。「実行とデバッグ」にはdry-run用の設定があります。

仮想環境の有効化は不要です。上記のようにPythonのパスを指定すれば、PowerShellのスクリプト実行ポリシーを変更せず利用できます。macOS/Linuxでは `.venv/bin/python` に読み替えてください。

## 2. 認証不要のdry-run

```powershell
.\.venv\Scripts\python.exe -m spreadsheet_cell_art --image "C:\Images\photo.jpg" --columns 100 --title "写真のモザイク" --dry-run --output-dir outputs\preview
```

元画像の寸法、EXIF補正後の寸法、描画する列数・行数・総セル数を表示し、以下を保存します。

- `preview.png`: 縮小結果そのもの。1セル分が1ピクセルです。
- `render.json`: 寸法、行優先のRGB配列、画像のSHA-256、セルサイズを含む設定、変換方式・データ形式のバージョン。
- `.run.lock`: 同じ出力先での同時実行を防ぐロック用ファイル。

dry-runではOAuth、トークン読み込み、Google API通信、`state.json`作成は行いません。Googleのライブラリを読み込む処理も実行しません。PNGとAPI送信には同じRGB配列を使います。PNGはセルのRGBを確認するためのもので、ブラウザのグリッド線表示を再現するものではありません。

## 3. Google CloudとOAuthの準備

操作は作品の保存に使用するご本人のGoogleアカウントで行ってください。

1. [Google Cloud Console](https://console.cloud.google.com/) にログインし、プロジェクトを作成または選択します。
2. 「APIとサービス」→「ライブラリ」で **Google Sheets API** を有効にします。
3. 「Google Auth Platform」の初期設定で、アプリ名、サポートメール、連絡先メールを登録します。
4. 個人のGoogleアカウントでは対象を「外部」にします。「テスト」状態の場合、ご自身のメールをテストユーザーに追加します。組織アカウントは管理者の設定に従ってください。
5. 「データアクセス」でスコープを登録する場合は `https://www.googleapis.com/auth/drive.file` を追加します。
6. 「クライアント」→「クライアントを作成」で **デスクトップ アプリ** を選択します。Webアプリやサービスアカウントは使用しません。
7. JSONをダウンロードし、以下の場所へ保存します。

```text
SpreadsheetCellArt/
  .secrets/
    client_secret.json
    token.json          # 初回認証の完了後に自動保存
```

`.secrets` は必要に応じて作成してください。認証情報の内容をチャットへ貼り付けたり、GitHubへアップロードしたりしないでください。`.gitignore` は `.secrets/`、`client_secret*.json`、`credentials*.json`、`token*.json` を除外します。カスタム保存先を使う場合もGit管理対象外にしてください。

本アプリはSheets APIの作成・取得・更新のみを使用します。`drive.file` スコープは、アプリが作成したファイルを扱うために使用し、Drive APIの呼び出しやDrive全体の権限は使用しません。

初回実行時にブラウザが開きます。ご本人がアカウントを選択し、アクセスを許可してください。認証結果は一時的なlocalhostのポートで受け取り、180秒で待機を終了します。以後は保存トークンを再利用し、期限切れなら更新します。

再認証が必要な場合は `--reauth` を付けます。トークンはOSの暗号化保管庫ではなくローカルJSONです。ログ・状態ファイルには記録しません。

参考: [Google公式Python quickstart](https://developers.google.com/workspace/sheets/api/quickstart/python)、[デスクトップOAuth](https://developers.google.com/identity/protocols/oauth2/native-app)。

## 4. 最初に20ピクセルを小さなシートで検証

```powershell
.\.venv\Scripts\python.exe -m spreadsheet_cell_art --probe --output-dir outputs\probe20
```

これは実際に検証用スプレッドシートを1ファイル作成します。画像ファイルは不要で、赤・緑／青・白の2×2セルを使います。処理順は次のとおりです。

1. `spreadsheets.create` で2行×2列のシートを1枚だけ作成。
2. **最初の更新**で全行と全列の `UpdateDimensionPropertiesRequest` をまとめて送り、双方 `pixelSize=20`、`fields="pixelSize"` に設定。
3. `spreadsheets.get` で全行・全列の `pixelSize` を取得し、すべて20であることを確認。
4. `hideGridlines=false` を明示し、グリッド線を表示。
5. `UpdateCellsRequest` で背景色のみ更新。
6. サイズ・グリッド線表示・全セルのRGBを再取得し、`verification.json` に保存。

**20pxの拒否・別値への補正・取得値の不足を検出した場合は停止し、別サイズへの変更は行いません。** 再取得した値は `state.json` の `size_verification` に保存します。最初のサイズ設定自体が拒否された場合、段階は `created` のままで着色しません。

完了時のURLをブラウザで開き、可能であればスプレッドシートとブラウザを100%表示で確認してください。OSの拡大率も記録すると比較できます。APIの寸法値と画面の物理ピクセルは同一の保証ではありません。セルとグリッド線を併用した際の色の見え方は、ブラウザで確認してください。

`verification.json` の `api_verified=true` はAPIの取得値が一致したという意味です。ブラウザ表示は自動判定せず `browser_display="未検証"` と記録します。表示上の問題があれば大きな作品の描画へ進まず、設定値と観察結果を分けて確認してください。

## 5. JPG画像を実描画

小さなシートで確認できた後に実行します。

```powershell
.\.venv\Scripts\python.exe -m spreadsheet_cell_art --image "C:\Images\photo.jpg" --columns 100 --title "写真のモザイク" --max-cells 100000 --output-dir outputs\photo --verify-colors
```

作品ごとに新しいファイルをマイドライブへ作成します。シート名は復旧時の照合用に `Mosaic_<実行識別子>` となります。完成時にURLを表示し、途中でも作成が確定した時点でURLを表示します。

各作品でも「全寸法20px→再取得確認→グリッド線表示→着色」の順序を守ります。セル結合、自動サイズ調整、描画中・描画後のセルサイズ拡大は行いません。文字・数式も書き込みません。

`--verify-colors` は追加で全セルの色を読み取り照合します。確認用の正方形JPEGで `--columns 100` を指定すると100×100セルになります。`state.json` の `drawing_seconds` は直近の実行で着色にかかった時間で、認証・初期化時間は含みません。

## 6. オプションと既定値

| オプション | 内容・既定値 |
|---|---|
| `--image` | JPG/JPEG。通常実行時に必須 |
| `--columns` | 横セル数。既定100 |
| `--title` | タイトル。既定は画像名と日時 |
| `--max-cells` | 総セル数上限。既定100,000 |
| `--batch-bytes` | JSON本文の上限。既定1,000,000バイト。これ以下に変更可能 |
| `--output-dir` | 既定 `outputs/<日時と識別子>/` |
| `--config` | TOML設定ファイル |
| `--dry-run` | 認証不要、PNG/JSONだけ保存 |
| `--resume` | 再開する `state.json` |
| `--adopt-spreadsheet` | 作成結果不明時の確認済みファイルID |
| `--credentials` | 既定 `.secrets/client_secret.json` |
| `--token` | 既定 `.secrets/token.json` |
| `--reauth` | ブラウザで再認証 |
| `--probe` | 組み込み2×2画像によるサイズと色の実測 |
| `--verify-colors` | 完了後の色の再取得（probeは自動で実施） |

設定ファイルの使用例:

```powershell
.\.venv\Scripts\python.exe -m spreadsheet_cell_art --config config.example.toml --image "C:\Images\photo.jpg" --dry-run
```

優先順位はCLI、TOML、既定値の順です。再開時は保存した設定を既定値として使い、明示指定が異なる場合は停止します。パスはカレントディレクトリ基準です。

縦セル数はEXIF補正後の縦横比から四捨五入し、最低1行を確保します。例: 4,000×3,000を横100指定なら100列×75行。整数化による最大半行程度の誤差があり、極端に細長い画像では最低1行の制約が優先されます。拡大は行わず、横セル数が元画像の補正後の横幅を超えた場合は停止します。

Pillowの `exif_transpose` → `convert("RGB")` → `Resampling.BOX` を使用します。RGB各成分の平均に相当する縮小で、物理的な光量平均やICCプロファイルの色管理ではありません。APIには各成分を255で割って渡します。初期版の対応列数上限は18,278列です。大きな画像・セル配列はメモリを消費するため、まず既定のセル上限を使用してください。

## 7. 途中から再開

```powershell
.\.venv\Scripts\python.exe -m spreadsheet_cell_art --resume outputs\photo\state.json
```

入力画像の場所、列数、タイトルなどは状態ファイルから復元します。画像内容のSHA-256、設定、RGBデータ、分割結果、進捗を照合し、保存された同じファイルID・シートIDへ続きを描きます。元画像を移動しただけの場合は `--image` で新しいパスを指定できます。

再開時も全行・全列が保存したセルサイズ（新規作品は20px）であることを確認し、グリッド線を表示します。サイズ設定が完了済みなら再設定しません。外部操作でシート名・行列数・サイズが変更されていれば停止します。描画済みセルを手で変更すると、完了済み範囲は再送しないため元へ戻りません。処理中の手動編集は避けてください。

旧版の状態ファイルはセルサイズの記録がないため、従来の1pxとして再開します。既存作品を20pxへ変更する機能ではありません。20pxで描き直す場合は `--resume` を付けず、同じ入力画像と新しい出力先で通常実行してください。

着色は同じ範囲に同じRGBを書くだけなので、応答途絶や保存前の中断で同じ要求を再送しても結果は変わりません。成功応答後に進捗を原子的に保存します。完了後に再開しても、着色は繰り返しません。

`--resume` では新しいファイルを作りません。作成前に停止した `prepared`、明確に作成拒否された `create_failed` は、原因を解消して別の出力先で通常実行してください。認証だけの失敗では状態ファイルを作成しないため、同じコマンドを再実行できます。

### 作成結果が不明な場合

新規ファイル作成は自動再送しません。通信切断・サーバーエラー・応答保存前の終了では `creation_unknown` を記録します。送信中に終了して `creating` が残った場合も、再開時に結果不明として扱います。

1. マイドライブで指定タイトルと作成時刻を探します。
2. `state.json` の `sheet_title` と、実際のシートタブ名が一致することを確認します。
3. 見つかったファイルのURLの `/d/` と `/edit` の間のIDを指定します。

```powershell
.\.venv\Scripts\python.exe -m spreadsheet_cell_art --resume outputs\photo\state.json --adopt-spreadsheet "確認したファイルID"
```

タイトル・実行固有のシート名・行列数をAPIでも照合し、全寸法の初期化から続行します。見つからない場合も自動再作成はせず、Driveの反映を待って再確認してください。結果不明の状態ファイルを削除して安易に再実行すると、重複ファイルを作る可能性があります。

## 8. 通信制御とエラー

- JSONの外側の構造・区切り・UTF-8化を含む本文の実容量で分割します。公式クライアントが生成した送信本文も直前に再計測します。
- 複数行をまとめて逐次送信します。1行が収まらない場合は列方向にも分割します。
- リクエスト間隔は最低1.1秒。初回以外は前回送信開始からの経過を考慮します。
- 更新・取得のHTTP 408/429/500/502/503/504、一時的な接続失敗、403のレート制限は最大5回再試行します。指数バックオフ＋ランダム値、待機上限32秒です。
- 入力不正、認証・権限不足、対象ファイル不明は日本語の原因・対処案内で停止します。APIエラー本文やトークンをそのまま出力しません。
- 作成は自動再試行の対象外です。明確な4xx拒否と、成否不明を区別します。
- 終了コード: 成功0、処理エラー1、CLI構文エラー2、中断130。

2026-09-28に確認した[公式利用制限](https://developers.google.com/workspace/sheets/api/limits)では、推奨本文上限2MB、読み取り・書き込みそれぞれ毎分300件/プロジェクト・60件/ユーザー/プロジェクト、処理タイムアウト180秒です。[ファイル容量の公式説明](https://support.google.com/drive/answer/37603)は最大2,000万セルと記載しています。アプリはユーザー指定のセル上限と、このセル数上限の小さい方を適用します。ファイル全体の容量や共有サービス側の制約まで事前に保証するものではありません。

| 症状 | 対応 |
|---|---|
| 入力が不正・上限超過 | 画像パス・JPEG実体・列数・セル上限を修正。Google上のファイル作成前に停止します |
| OAuthクライアントが見つからない | デスクトップ用JSONの配置、または `--credentials` を確認 |
| 「審査プロセスを完了していません」「承認されたテスターのみ」 | Google Auth Platform → 対象（Audience）→ テストユーザーに、認証に使うメールアドレスを追加・保存。認証待ちをCtrl+Cで終了して再実行 |
| トークン失効 | `--reauth` を付けてご本人で再認証 |
| API無効のHTTP 403 | OAuthクライアントと同じプロジェクトでGoogle Sheets APIを有効化し、反映後に再実行。作成拒否済みの出力先はそのまま保存し、新しい出力先を指定 |
| スコープ不足のHTTP 403 | `--reauth` で再認証し、drive.fileの許可を確認 |
| その他のHTTP 403 | アカウント、ファイルの権限、保存容量、組織側制限を確認 |
| 指定サイズが保持されない | `size_verification` を確認。別サイズに変更して続行する機能はありません |
| 再試行上限 | 通信状況が戻った後に `--resume` |
| 状態不一致 | 元画像・設定・ライブラリ/アプリ版を確認。状態ファイルを手で書き換えない |
| 同時実行エラー | 同じ出力先の処理が終了するまで待つ。ロックはプロセス終了時にOSが解放します |

## 9. テスト・TDD

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

すべてのpytestはGoogle接続・認証情報なしで実行します。公式クライアントを使うテストも通信先を置き換えています。画像変換、2×2の色と配置、20px初期化順序、グリッド線表示、実バイト数による分割、dry-run、認証更新、再試行、保存失敗、二重起動、再開、旧1px作品の互換性、作成結果不明の復旧を検証します。JPEGは非可逆圧縮のため、厳密な色配置テストにはメモリ上のRGB画像を使います。

[todo.md](todo.md) に優先タスクとRed→Green→リファクタリングの記録を残します。新たに判明した事象はテストを先に追加して修正します。実接続未実施の項目は未完了として残します。

## 10. 構成とGitHub

| ファイル | 責務 |
|---|---|
| `imaging.py` | JPEG検証・EXIF・RGB・BOX縮小・ハッシュ |
| `render_data.py` / `preview.py` | 共通描画データ・PNG/JSON |
| `requests.py` / `batching.py` | API要求・送信分割 |
| `auth.py` / `sheets_api.py` | Google認証・通信・再試行 |
| `state.py` / `runner.py` | 状態・ロック・処理順序・再開 |
| `verification.py` | API再取得による検証記録 |
| `config.py` / `cli.py` | 設定・日本語CLI |

Miro版のEXIF/BOX・画像ハッシュ・原子的保存の考え方を再利用しています。実行時にMiro版のフォルダーやライブラリは必要ありません。

GitHub Actionsの定義を同梱し、Windows/Ubuntu、Python 3.11/3.13でオフラインテストを行う構成にしています。Actionsの実行結果は、実際にGitHubへpushした後に確認してください。

GitHubへの公開時は、ご本人の環境で認証・接続を確認してください。

```powershell
git status --short
git remote -v
git add .
git diff --cached --stat
git commit -m "Implement Google Sheets cell art CLI"
git push -u origin main
```

追加対象に認証情報・トークン・入力画像・出力作品が含まれていないことを確認してからコミットします。作業用リポジトリに既にremoteが設定されている場合、設定を重ねて追加する必要はありません。
