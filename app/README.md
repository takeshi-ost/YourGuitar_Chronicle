# Your Guitar Chronicle — ローカル試作

ギター個体の来歴をClaim中心に保存・表示するFastAPI + SQLiteのローカルアプリ。公開サービス向けの本人確認・権限検査はまだない。Reverbからの収集は公式APIを使う。設計と現行機能は [ドキュメント一覧](../docs/README.md) を参照。

## 開始

Python 3.12以降を用意して、この `app` ディレクトリで実行する。

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

macOSはリポジトリ直下の `start_webui.command`、Windowsは `start_webui.bat` でも起動できる。手動起動は次の通り。

```bash
ygc init-db
ygc-web
```

表示されたlocalhostのURLを開く。`/` は管理用Browser Console、`/user-view` はゲストも閲覧できるTop Page。ローカルの操作用ユーザー選択は**ログインではない**。Browser Consoleの管理トークンは同じプロセス・localhostでだけ有効。

## Reverbの収集

Reverb Personal Access Tokenを読み取りに必要な最小権限で用意し、Browser Consoleのトークン欄、または環境変数 `REVERB_API_TOKEN` に設定する。トークンをGitにコミットしない。

- **Batch Crawl:** 任意の検索語を1行ずつ入力する。
- **Incremental Crawl:** 分野と製造年範囲を指定し、Advanceを押すたびに次へ進む。1回の一覧処理は最大2000件。対象候補の詳細に別の件数上限はない。
- **保存済み詳細を再判定:** 保存したReverbレスポンスをネットワークアクセスなしで再抽出・照合する。
- CLIで1ステップ進める場合は `ygc crawl-step --category electric --year-min 1950 --year-max 1980`。

収集の条件・再開・統計の定義は [incremental-crawl.md](../docs/incremental-crawl.md)。古いDBは収集前に `ygc claim-status` でreadinessを確認し、必要ならバックアップ後 `ygc migrate-claims` を実行する。管理画面のDB初期化・復元操作はバックアップを確認してから行う。`ygc init-db` は既存DBの初期化・互換列追加を行う。

## ローカルデータと設定

既定のSQLiteは `app/data/chronicle.db`、画像は `app/data/media` に保存される。保存先は `YGC_DATA_DIR` / `YGC_DB_PATH`、Reverbへの間隔は `YGC_REQUEST_DELAY` などで変更できる。**DBと画像を一緒にバックアップする**。管理画面のエクスポート／復元はローカル試作用である。

Cloud Runではこの構成を動かさず、未実装のGCPアダプターを要求して起動を止める。交換箇所と残作業は [GCP_BOUNDARIES.md](../docs/GCP_BOUNDARIES.md)。
