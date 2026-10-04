# Your Guitar Chronicle — ローカル試作

ギター個体の来歴をClaim中心に保存・表示するFastAPI + SQLiteのローカルアプリ。公開サービス向けの本人確認・権限検査はまだない。Reverbからの収集は公式APIを使う。設計と現行機能は [ドキュメント一覧](../docs/README.md) を参照。

## 開始

Python 3.12以降を用意して、この `app` ディレクトリで実行する。

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python ../scripts/install_dependencies.py
```

## テスト

Python 3.12以降とNode.jsを用意し、リポジトリ直下で実行する。

```bash
app/.venv/bin/python scripts/run_tests.py
```

Windowsでは `app\.venv\Scripts\python.exe scripts/run_tests.py`。仮想環境を有効化済みなら `python scripts/run_tests.py` でもよい。Node.jsがPATHにない場合は `--node /path/to/node` を指定する。PythonとJavaScriptを両方実行し、いずれかの失敗は終了コード1で返す。テストは実データ・認証情報を継承せず、一時ディレクトリを終了時に削除する。Reverbトークンは不要。

ブラウザ検証も実行する場合は、`app` 内で `python ../scripts/install_dependencies.py --browser`、`python -m playwright install chromium` を実行してから、共通コマンドに `--browser` を付ける。既存Chromeを使う場合は `--browser-executable /path/to/chrome` も指定できる。専用の一時DB・画像・ローカルサーバーを自動生成し、終了時に停止・削除する。既存の起動中サーバーには接続しない。ローカル通信が禁止された実行環境では、通信を許可して実行する必要がある。

個別のPythonテストは `app` 内の `python -m pytest tests/test_ui_assets.py -q` などでも実行できる。`tests/conftest.py` がアプリの読み込み前に保存先を一時領域へ切り替え、各テストにも独立したDB・画像・ログ領域を用意する。呼び出し元の `YGC_DATA_DIR`／DBパスは使用しない。


macOSはリポジトリ直下の `start_webui.command`、Windowsは `start_webui.bat` でも起動できる。手動起動は次の通り。

```bash
ygc init-db
ygc-web
```

表示されたlocalhostのURLを開く。`/` は管理用Browser Console、`/user-view` はゲストも閲覧できるTop Page。`ygc-web` はローカルダミー認証・アカウントDB分離モードで起動する。初回起動時に既存DBの安全用コピーを保存して移行し、以後は `accounts.sqlite` とChronicleを独立してバックアップ／復元できる。テストユーザーの選択で認証成功を代用するため、実際の本人確認を行うものではない。Browser Consoleの管理トークンは同じプロセス・localhostでだけ有効。

CLIや `uvicorn ygc.web:app` も同じデータを扱う場合は `YGC_IDENTITY_BACKEND=local_dummy` を設定する。分離前の互換動作は `ygc-web --identity-backend prototype` で利用できるが、分離済みデータでは拒否する。詳しい保存対象・移行条件は [ローカル認証とアカウント分離](../docs/GCP_BOUNDARIES.md#ローカル実装アカウント分離とダミー認証) を参照。

## Reverbの収集

Reverb Personal Access Tokenを読み取りに必要な最小権限で用意し、Browser Consoleのトークン欄、または環境変数 `REVERB_API_TOKEN` に設定する。トークンをGitにコミットしない。

- **Batch Crawl:** 任意の検索語を1行ずつ入力する。
- **Incremental Crawl:** 分野と製造年範囲を指定し、Advanceを押すたびに次へ進む。1回の一覧処理は最大2000件。対象候補の詳細に別の件数上限はない。
- **保存済み詳細を再判定:** 保存したReverbレスポンスをネットワークアクセスなしで再抽出・照合する。
- CLIで1ステップ進める場合は `ygc crawl-step --category electric --year-min 1950 --year-max 1980`。

収集の条件・再開・統計の定義は [incremental-crawl.md](../docs/incremental-crawl.md)。古いDBは収集前に `ygc claim-status` でreadinessを確認し、必要ならバックアップ後 `ygc migrate-claims` を実行する。管理画面のDB初期化・復元操作はバックアップを確認してから行う。`ygc init-db` は既存DBの初期化・互換列追加を行う。

現在値は共通Observation評価器から生成する。`ygc audit-observation-migration --sample-limit 20` は保存済みSnapshotと再評価結果、掲載・取得日のEvidence欠損を読み取り専用で照合する。`claim-status` は起動時のスキーマ更新を含むため、完全な読み取り専用監査とは異なる。旧DBのEvidence複写と互換処理の整理手順は [Observation移行の残作業](../docs/TEMP_OBSERVATION_MIGRATION_PLAN.md) を参照。

`ygc show ID` はClaimによる来歴を表示する。旧履歴オプションは廃止済み。個体詳細APIは旧 `observations` を返さず、作成APIは旧Observation IDの代わりにClaim IDを返す。Claim編集は旧履歴に同期しない。

未登録クロール記録は、バックアップ後に `ygc archive-unregistered-crawl` で全列を専用保管先へ複写できる。元行の削除・上書きは行わず、不一致時は複写全体を取り消す。まずDBコピーで確認する。保管先には期限を設けず、元行がなくても既知Listing判定と公開状態確認に使用できる。

新規の未登録記録は `crawl_unregistered_records` に入力全体を保存し、旧Observationを作成しない。`ygc stats` は旧行数ではなく、既知外部掲載数・シリアル付き登録掲載数・その比率を表示する。詳細な集計定義と旧APIの撤去内容は上記の移行文書を参照。

## ローカルデータと設定

既定のSQLiteは `app/data/chronicle.db`、画像は `app/data/media` に保存される。保存先は `YGC_DATA_DIR` / `YGC_DB_PATH`、Reverbへの間隔は `YGC_REQUEST_DELAY` などで変更できる。**DBと画像を一緒にバックアップする**。管理画面のエクスポート／復元はローカル試作用である。

Cloud Runではこの構成を動かさず、未実装のGCPアダプターを要求して起動を止める。交換箇所と残作業は [GCP_BOUNDARIES.md](../docs/GCP_BOUNDARIES.md)。

## 依存関係の固定

`constraints.txt` が直接・間接依存の固定バージョンを持つ。`pyproject.toml` は必要なライブラリと対応範囲を定義する。セットアップと起動スクリプトは `scripts/install_dependencies.py` を使い、pip自体、実行時依存、ビルド時依存を固定する。通常は開発用、`--runtime` は実行用のみ、`--browser` はブラウザ検証用も追加する。既存環境の追加パッケージは削除しないため、本番・CIは新しい仮想環境を使用する。

依存更新は起動時には行わない。変更が必要なときに、リポジトリ直下で次を実行し、固定ファイルの差分と共通テストを確認する。再生成にはuvが必要だが、通常のインストールにuvは不要。

```bash
uv pip compile app/pyproject.toml app/build-requirements.txt --all-extras --universal --python-version 3.12 --output-file app/constraints.txt
```

既存バージョンは再生成時にも優先する。意図的に更新する場合だけ `--upgrade-package パッケージ名` を追加する。ビルド依存を変える場合は `pyproject.toml` と `build-requirements.txt` も揃える。OS固有の依存はマーカーで管理する。Pythonは現在検証済みの3.12を基準とし、Windows/Linuxの実機検証とCIは別途実施する。Node.jsはPython依存に含まず、JavaScriptテスト用に別途用意する。

## PR自動チェック

`.github/workflows/pr-checks.yml` はmain向けPRの作成・更新、mainへのpush、手動実行で動く。Ubuntu 24.04、Python 3.12、Node.js 24で、固定依存とPlaywrightのChromiumをインストールし、`python scripts/run_tests.py --browser` を実行する。実データ・GCP・Reverbへの接続情報は不要。新しい更新が届いたら同じPRの古い実行はキャンセルする。

GitHub上のチェック名は `Tests (Python, JavaScript, Chromium)`。失敗した場合はPRのChecksから該当ステップのログを確認する。自動チェックを必須のマージ条件にする場合はmainの保護ルールでこの名前をRequired status checksへ追加する。ワークフローだけではマージを禁止しない。チェックはLinuxでの実機検証も兼ねるが、Windowsでの実機検証はまだ含まない。
