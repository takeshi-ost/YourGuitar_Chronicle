# 開発・検証・PR運用

テスト・依存固定・PRチェック・一時領域の後片付けを扱う。変更履歴はPR #13を参照。セットアップ・起動は[app/README.md](../../app/README.md)。

## テスト

Python 3.12以降とNode.jsを用意し、リポジトリ直下で実行する。

```bash
app/.venv/bin/python scripts/run_tests.py
```

Windowsでは `app\.venv\Scripts\python.exe scripts/run_tests.py`。仮想環境を有効化済みなら `python scripts/run_tests.py` でもよい。Node.jsがPATHにない場合は `--node /path/to/node` を指定する。PythonとJavaScriptを両方実行し、いずれかの失敗は終了コード1で返す。テストは実データ・認証情報を継承せず、一時ディレクトリを終了時に削除する。Reverbトークンは不要。

ブラウザ検証も実行する場合は、`app` 内で `python ../scripts/install_dependencies.py --browser`、`python -m playwright install chromium` を実行してから、共通コマンドに `--browser` を付ける。既存Chromeを使う場合は `--browser-executable /path/to/chrome` も指定できる。専用の一時DB・画像・ローカルサーバーを自動生成し、終了時に停止・削除する。既存の起動中サーバーには接続しない。ローカル通信が禁止された実行環境では、通信を許可して実行する必要がある。

個別のPythonテストは `app` 内の `python -m pytest tests/test_ui_assets.py -q` などでも実行できる。`tests/conftest.py` がアプリの読み込み前に保存先を一時領域へ切り替え、各テストにも独立したDB・画像・ログ領域を用意する。呼び出し元の `YGC_DATA_DIR`／DBパスは使用しない。


## 依存関係の固定

`constraints.txt` が直接・間接依存の固定バージョンを持つ。`pyproject.toml` は必要なライブラリと対応範囲を定義する。セットアップと起動スクリプトは `scripts/install_dependencies.py` を使い、pip自体、実行時依存、ビルド時依存を固定する。通常は開発用、`--runtime` は実行用のみ、`--browser` はブラウザ検証用、`--postgres` はPostgreSQL接続・移行用を追加する。既存環境の追加パッケージは削除しないため、本番・CIは新しい仮想環境を使用する。

依存更新は起動時には行わない。変更が必要なときに、リポジトリ直下で次を実行し、固定ファイルの差分と共通テストを確認する。再生成にはuvが必要だが、通常のインストールにuvは不要。

```bash
uv pip compile app/pyproject.toml app/build-requirements.txt --all-extras --universal --python-version 3.12 --output-file app/constraints.txt
```

既存バージョンは再生成時にも優先する。意図的に更新する場合だけ `--upgrade-package パッケージ名` を追加する。ビルド依存を変える場合は `pyproject.toml` と `build-requirements.txt` も揃える。OS固有の依存はマーカーで管理する。Pythonは現在検証済みの3.12を基準とし、Windows/Linuxの実機検証とCIは別途実施する。Node.jsはPython依存に含まず、JavaScriptテスト用に別途用意する。

## PR自動チェック

`.github/workflows/pr-checks.yml` はmain向けPRの作成・更新、mainへのpush、手動実行で動く。Ubuntu 24.04、Python 3.12、Node.js 24で、固定依存とPlaywrightのChromiumをインストールし、専用PostgreSQL 18サービスを起動し、`python scripts/build_postgres_schema.py --check` と `python scripts/run_tests.py --browser --postgres-port 5432` を実行する。実データ・GCP・Reverbへの接続情報は不要。新しい更新が届いたら同じPRの古い実行はキャンセルする。

GitHub上のチェック名は `Tests (Python, JavaScript, Chromium)`。失敗した場合はPRのChecksから該当ステップのログを確認する。ブラウザ失敗時は `browser-failure-diagnostics` artifactにスクリーンショット・Playwright trace・ページエラーを保存し、7日間保持する。実データ・実認証情報を使わない専用テスト環境の記録。2026-10-04にmainの保護ルールへこのチェックを登録済み。PR経由と最新mainに対するチェック成功を管理者にも要求する。他者レビュー承認は必須ではなく、強制push・ブランチ削除は許可しない。チェックはLinuxでの実機検証も兼ねるが、Windowsでの実機検証はまだ含まない。

テストの後片付け：pytestの `tmp_path` とキャッシュも専用の一時保存先にまとめ、成功・失敗・通常のCtrl+C中断でPythonプロセスが終了した際に削除する。削除対象を安全に限定するため、独自の `--basetemp` 指定は受け付けない。OSによる強制終了（SIGKILL）や電源断では終了処理が走らず、一時領域が残る場合がある。以前の実行で残った領域は今回の自動削除対象に含めない。

## 残る整備と確認済み状態

残作業の優先度・完了条件・移行作業との区別は[GCP移行前の整備状況](GCP_PREPARATION_STATUS.md)で管理する。

PR #14の統合後main `aa27c21` でもCI成功。Python435件、JavaScript55件、Chromiumの共通UI・モーダル・主要ユーザー操作の検証が通過した。件数は固定の合格条件にしない。mainの保護ルールは適用済み。依存整合検査・主要操作のブラウザテスト・失敗artifactはPR #14でmainへ統合・CI検証済み。Windows実機確認は残る。

## 追加した移行前チェック

ブラウザ依存まで導入した環境で `python scripts/check_dependencies.py` を実行する。直接・任意依存の固定漏れ、定義範囲との不一致、ビルド定義とbuild-requirementsの差、インストール済みパッケージの間接依存の固定漏れを検出する。CIでは依存導入直後に実行する。OS非該当パッケージのインストール確認は行わず、ビルドバックエンドはpipの隔離環境に入るためファイル定義を照合する。全OSの解決結果を再生成して一致比較する検査ではない。

ブラウザの定常検証には日本語切替・再読込、ローカル登録と同意、入力メール／パスワードの送信禁止、既存ユーザーのサインイン・SignOut、Listing提出から新規登録、Acquire提出からOwner承認を含める。GPTの観察結果だけを固定のテストデータで供給する。外部のGPT・Identity Platform・Reverbへ接続する検証ではない。

ローカルで診断を残す場合は共通コマンドへ `--browser-artifacts /path/to/diagnostics` を付ける。成功時には診断ファイルを生成せず、失敗時に保存する。指定先は自動削除対象の一時DBとは別に保持する。ブラウザの実行・記録は `browser_diagnostics.py` で共通化する。

## PostgreSQL移行基盤の検証

接続・4スキーマ・権限・再実行の検証手順は[PostgreSQL初期化](../migration/POSTGRES_BOOTSTRAP.md)。ローカルは `--postgres-bin /path/to/postgresql18/bin` で一時クラスタを使う。依存の全固定検査には `scripts/install_dependencies.py --browser --postgres --identity` で全extrasを導入する。WebUIのPostgreSQL移植とは別段階。
