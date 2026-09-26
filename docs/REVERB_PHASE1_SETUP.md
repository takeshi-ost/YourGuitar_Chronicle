# Your Guitar Chronicle Phase 0 — Reverb API セットアップとリスト生成手順

このドキュメントは、**Your Guitar Chronicle (YGC) Phase 0** を別のPC／開発環境で再現し、Reverb API の Personal Access Token を取得して、Vintage Guitar の Observation / Individual リストを生成するまでの手順をまとめたものです。

対象は現在の Phase 0 実装です。Reverb の公開 Listing を公式 API 経由で取得し、Vintage 判定、Serial Number 抽出、Individual 生成を行います。

## 1. 前提

必要なもの:

- Git
- Python 3.12 以上
- Reverb アカウント
- Your Guitar Chronicle のリポジトリ
- インターネット接続

Windows PowerShell を基準に記載します。

## 2. Reverb Personal Access Token を取得する

YGC Phase 0 は Reverb の HTML をスクレイピングせず、**Reverb 公式 API** を利用します。

Reverb 公式ドキュメント:

- Authentication / Personal Token: https://www.reverb-api.com/docs/authentication
- Getting Started: https://www.reverb-api.com/docs/getting-started

### 手順

1. Reverb にログインする。
2. ユーザーメニューから **My Profile** を開く。
3. **API & Integrations** タブを開く。
4. **Generate New Token** を押す。
5. Token 名を入力する。
6. 必要な Scope を選択して Token を生成する。

Phase 0 は公開 Listing の読み取りが目的なので、書き込み権限は不要です。可能な限り読み取りに必要な最小権限だけを使用してください。

Reverb の Personal Access Token は公式ドキュメント上、期限切れしません。

### 重要: Token を Git にコミットしない

Token はパスワードと同等に扱います。

Python ファイル、README、設定ファイルなどに実際の Token 文字列を直接書いて commit しないでください。Token は環境変数として設定します。

## 3. リポジトリを取得する

```powershell
git clone <YOUR_GITHUB_REPOSITORY_URL>
cd YourGuitar_Chronicle\phase0_proto
```

すでに clone 済みなら対象ディレクトリへ移動します。

## 4. Python 仮想環境を作成する

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

PowerShell の先頭に `(.venv)` が出れば有効です。

## 5. YGC Phase 0 をインストールする

```powershell
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

CLI 確認:

```powershell
ygc --help
```

## 6. Reverb Token を環境変数へ設定する

```powershell
$env:REVERB_API_TOKEN="ここに取得したToken"
```

確認:

```powershell
$env:REVERB_API_TOKEN
```

PowerShell を閉じると、この方法で設定した値は消えます。

## 7. Reverb API 接続確認

```powershell
ygc reverb-probe --query "Fender Stratocaster"
```

現在の実装では Reverb API に以下の Header を使います。

```text
Authorization: Bearer <TOKEN>
Accept: application/hal+json
Content-Type: application/hal+json
Accept-Version: 3.0
```

## 8. 1件の Listing 詳細を確認する

```powershell
ygc reverb-sample --query "Fender Stratocaster"
```

主に利用する項目:

```text
id
make
model
year
title
description
shop_name / shop
published_at
categories
_links
```

Serial Number は常に構造化フィールドとして存在するわけではないため、YGC では title と description のテキストから抽出します。

## 9. テストを実行する

```powershell
pytest -q
```

必要なら個別に構文確認:

```powershell
python -m py_compile src\ygc\collectors\reverb.py
python -m py_compile src\ygc\extractors\serial.py
python -m py_compile src\ygc\reverb_adapter.py
python -m py_compile src\ygc\cli.py
```

## 10. データベースを初期化する

```powershell
ygc init-db
```

テスト用 DB を完全に作り直す場合:

```powershell
Remove-Item data\chronicle.db
ygc init-db
```

## 11. Vintage 判定を確認する

```powershell
ygc vintage-audit --query "Fender Stratocaster" --limit 100
```

現在の分類:

```text
vintage
modern
unknown
non_target
```

主な方針:

- Reverb の構造化 `year` を優先
- タイトル中の信頼できる年式を次に使う
- description 中の古い年号だけでは Vintage と判定しない
- `Custom Shop`, `American Vintage`, `American Vintage II`, `Time Capsule`, `Reissue`, `Vintera`, `Anniversary`, `Historic`, `Tribute` などは現代製品判定の材料にする
- 現在の Phase 0 では概ね 1980 年以前を Vintage 自動収集対象とする

これはサービスへの登録条件ではなく、自動収集の対象を絞るための Phase 0 上のルールです。

## 12. Listing をクロールする

100件で試す:

```powershell
ygc crawl --query "Fender Stratocaster" --limit 100
```

問題なければ500件:

```powershell
ygc crawl --query "Fender Stratocaster" --limit 500
```

現在の高速化版では:

1. Listing summary をまとめて取得
2. Summary で Vintage / Modern / Unknown / Non-target を分類
3. Modern / Non-target を除外
4. 既取得 Listing を除外
5. 候補だけ詳細 API を取得
6. 詳細取得は少数並列
7. Serial Number を抽出
8. Observation を保存
9. Maker + Model + Serial を使って Individual を生成

並列数指定:

```powershell
ygc crawl --query "Fender Stratocaster" --limit 500 --workers 6
```

## 13. 複数モデルを収集する

```powershell
ygc crawl --query "Fender Stratocaster" --limit 500
ygc crawl --query "Fender Telecaster" --limit 500
ygc crawl --query "Fender Jazzmaster" --limit 500
ygc crawl --query "Fender Jaguar" --limit 500
ygc crawl --query "Gibson Les Paul" --limit 500
ygc crawl --query "Gibson SG" --limit 500
ygc crawl --query "Gibson ES-335" --limit 500
```

同じ Reverb Listing が別クエリにも出た場合、既存 `source_listing_id` を確認して再取得を抑制します。

## 14. 収集結果を確認する

統計:

```powershell
ygc stats
```

Individual 一覧:

```powershell
ygc individuals
```

特定 Individual の履歴:

```powershell
ygc show 1
```

重要な統計:

```text
observations
serial_observations
serial_extraction_rate
individuals
repeated_individuals
max_observations_per_individual
```

## 15. Serial Number 抽出を監査する

```powershell
ygc serial-audit
```

`MATCH` は DB 保存時の SN と現在の extractor が再抽出した SN が一致したことを意味します。

実際にギター本体の Serial Number であるかは `Context` も目視確認してください。

良い例:

```text
Serial: 524436
```

現在確認されている誤抽出例:

```text
THATDATESTO1964
DATESTO1965
DATEBACKTO1976
73178142--YOUR
L6XXXX
```

このため Serial validation は今後の改善対象です。

## 16. 現時点で確認済みの Phase 0 動作

```text
Reverb API
    ↓
Listing summary
    ↓
Vintage candidate filtering
    ↓
Listing detail
    ↓
Serial extraction
    ↓
Observation
    ↓
Individual
```

確認済みの正例:

```text
Fender Stratocaster - Natural - 1974 - 2nd Hand
Serial: 524436
```

`serial-audit` でも同じ Serial が再抽出され、`MATCH` になることを確認しています。

複数モデルを数千件規模で検索した時点では、256 Observations、41 Serial Observations、41 Individuals が生成されています。一方で repeated_individuals はまだ 0 です。

## 17. Chronicle の成立を確認する指標

重要な Phase 0 KPI:

```text
repeated_individuals
max_observations_per_individual
```

同一 Maker / Model / Serial のギターが別 Listing として再登場すると、複数 Observation が同一 Individual に紐づきます。

```text
repeated_individuals > 0
max_observations_per_individual > 1
```

となれば、

**「公開市場データから同一ギターの Chronicle が自動的に蓄積される」**

という中心仮説を実データで確認できます。

## 18. セキュリティ上の注意

`.gitignore` の例:

```gitignore
.env
*.env
data/chronicle.db
```

- Token を commit しない
- Token をログへ出さない
- Token を Issue / Pull Request / スクリーンショットへ貼らない
- 漏洩した場合は Reverb 側で Token を無効化し、新しく生成する

## 19. macOS / Linux の Token 設定

```bash
export REVERB_API_TOKEN="..."
```

確認:

```bash
echo "$REVERB_API_TOKEN"
```

## 20. 最短セットアップ手順

```powershell
cd YourGuitar_Chronicle\phase0_proto

python -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -e ".[dev]"

$env:REVERB_API_TOKEN="YOUR_REVERB_PERSONAL_ACCESS_TOKEN"

pytest -q

ygc init-db

ygc reverb-probe --query "Fender Stratocaster"
ygc vintage-audit --query "Fender Stratocaster" --limit 100
ygc crawl --query "Fender Stratocaster" --limit 500

ygc stats
ygc individuals
ygc serial-audit
```

## 参考: Reverb 公式 API ドキュメント

- Reverb API Home: https://www.reverb-api.com/
- Getting Started: https://www.reverb-api.com/docs/getting-started
- Authentication / Personal Access Token: https://www.reverb-api.com/docs/authentication
- Listing Details: https://www.reverb-api.com/docs/updating-your-listing

_Last updated: 2026-09-23_
