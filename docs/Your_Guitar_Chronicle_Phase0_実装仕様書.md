# Your Guitar Chronicle — Phase 0 実装仕様書

## 0. 文書の目的

本書は、企画書 **「Your Guitar Chronicle 企画書（改訂案）」** を前提として、Phase 0「Local Chronicle Engine」をCodex等の実装エージェントが迷わず着手できる粒度まで具体化した実装仕様書である。

Phase 0の目的は、公開サービスを作ることではない。

**ローカルPC上で、Web上の商品情報からギター個体の最小情報を取得し、同一個体の再出現をObservationとして蓄積し、Chronicleが自動形成されることを検証する。**

---

# 1. Phase 0 のゴール

Phase 0では、以下の一連の処理がローカル環境で動作することをゴールとする。

```text
対象Webページを取得
    ↓
ギター商品ページを解析
    ↓
メーカー / モデル / シリアル番号 / 出品者を抽出
    ↓
ObservationとしてDBへ保存
    ↓
既存Individualと照合
    ↓
同一個体なら既存IndividualへObservation追加
新規ならIndividual作成
    ↓
Chronicle（時系列）として確認
```

Phase 0では、クロール件数や対応サイト数を増やすことよりも、**このパイプラインを小さく最後まで完成させること**を優先する。

---

# 2. Phase 0 の非目標

以下はPhase 0では実装しない。

- ユーザー登録
- ログイン
- 所有Claim
- Evidence
- Attestation
- コメント
- SNS機能
- サーバー公開
- クラウドDB
- 課金
- 広告
- 法的所有権の判定
- 強制移譲
- 14日タイマー
- 画像OCR
- 画像類似度判定
- AIによる完全自動マージ
- 複数ユーザーによる共同編集
- 高度な信頼度スコア
- 検索エンジン最適化
- 大規模分散クロール
- 全Webサイト対応

---

# 3. 対象範囲

## 3.1 初期対象サイト

最初は **1サイトのみ** を対象とする。

第一候補は以下のいずれかとする。

1. Reverb
2. デジマート
3. eBay
4. Yahoo!オークション

ただし、実装開始時に以下を確認する。

- robots.txt
- 利用規約
- 公開HTMLで取得可能な情報
- robots / 利用規約上の制約
- API提供の有無
- ログイン必須か
- JavaScriptレンダリング必須か

利用条件上の問題がある場合は、無理に回避せず、対象サイトを変更する。

Phase 0では**アクセス制限やボット対策の突破を目的としない**。

---

## 3.2 対象商品の考え方

自動収集対象は、企画方針に従い、主に以下を優先する。

- ビンテージギター
- コレクタブルギター
- 希少モデル
- 廃番モデル
- 高額個体
- Custom Shop
- 限定モデル
- 手工品
- 来歴追跡価値が高い個体

ただしPhase 0では高度な価値判定ロジックを実装せず、対象サイト内の検索URLやカテゴリを利用して対象を絞る。

例：

```text
Vintage Electric Guitar
Fender Vintage
Gibson Vintage
Pre-1980 Guitar
```

---

# 4. 技術スタック

Phase 0では以下を標準構成とする。

## 4.1 言語

**Python 3.12 以上**

理由：

- Web収集
- HTML解析
- NLP
- SQLite
- データ分析
- 将来的なAI処理

との相性が良い。

---

## 4.2 推奨ライブラリ

### HTTP / Browser

優先順位：

1. `httpx`
2. `requests`
3. `Playwright`

通常HTML取得で十分な場合は `httpx` を使用する。

JavaScriptレンダリングが必須の場合のみPlaywrightを使用する。

---

### HTML解析

- `BeautifulSoup4`
- `lxml`

---

### DB

- `SQLite`
- Python標準 `sqlite3`

Phase 0ではORMを必須としない。

ただし、実装が整理しやすい場合はSQLAlchemyを使用してもよい。

---

### CLI

- `argparse` または `Typer`

---

### テスト

- `pytest`

---

### データ検証

必要に応じて：

- `pydantic`

---

# 5. ディレクトリ構成

初期構成は以下を推奨する。

```text
your-guitar-chronicle/
│
├─ README.md
├─ pyproject.toml
├─ .gitignore
│
├─ data/
│   ├─ chronicle.db
│   └─ samples/
│
├─ src/
│   └─ ygc/
│       ├─ __init__.py
│       │
│       ├─ collectors/
│       │   ├─ __init__.py
│       │   ├─ base.py
│       │   └─ target_site.py
│       │
│       ├─ extractors/
│       │   ├─ __init__.py
│       │   ├─ manufacturer.py
│       │   ├─ model.py
│       │   ├─ serial.py
│       │   └─ seller.py
│       │
│       ├─ matching/
│       │   ├─ __init__.py
│       │   └─ individual_matcher.py
│       │
│       ├─ db/
│       │   ├─ __init__.py
│       │   ├─ schema.sql
│       │   └─ repository.py
│       │
│       ├─ cli.py
│       └─ config.py
│
└─ tests/
    ├─ fixtures/
    ├─ test_serial_extractor.py
    ├─ test_matching.py
    └─ test_repository.py
```

---

# 6. データモデル

Phase 0では、DB構造を複雑にしすぎない。

最低限、以下の3テーブルを使用する。

---

## 6.1 individuals

現実世界の1本のギターを表す。

```sql
CREATE TABLE individuals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    manufacturer TEXT NOT NULL,
    model TEXT,
    serial_number TEXT,

    normalized_manufacturer TEXT NOT NULL,
    normalized_model TEXT,
    normalized_serial TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

---

## 6.2 observations

Web上で確認された1回の出現記録。

```sql
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    individual_id INTEGER,

    manufacturer TEXT,
    model TEXT,
    serial_number TEXT,
    seller TEXT,

    source_site TEXT NOT NULL,
    source_url TEXT NOT NULL,

    observed_at TEXT NOT NULL,
    listing_date TEXT,

    title TEXT,
    raw_text TEXT,

    serial_confidence REAL,
    extraction_version TEXT,

    created_at TEXT NOT NULL,

    FOREIGN KEY(individual_id)
        REFERENCES individuals(id)
);
```

---

## 6.3 crawl_runs

クロール実行単位を記録する。

```sql
CREATE TABLE crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    source_site TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,

    pages_discovered INTEGER DEFAULT 0,
    pages_fetched INTEGER DEFAULT 0,
    observations_created INTEGER DEFAULT 0,

    status TEXT NOT NULL,
    error_message TEXT
);
```

---

# 7. 正規化ルール

同一個体判定のため、表示用データと照合用データを分ける。

例：

```text
manufacturer:
"Fender"

normalized_manufacturer:
"fender"
```

---

## 7.1 Manufacturer

以下を行う。

- 前後空白削除
- 小文字化
- 連続空白除去
- 既知表記揺れ統合

例：

```text
FENDER
Fender USA
Fender Musical Instruments

→ fender
```

Phase 0では巨大な辞書は作らない。

まず主要ブランドのみ。

例：

- Fender
- Gibson
- Gretsch
- Martin
- Rickenbacker

---

## 7.2 Model

以下を基本とする。

- 小文字化
- 前後空白削除
- 連続空白除去
- 記号の軽度正規化

例：

```text
Telecaster Thinline
TELECASTER THINLINE
Telecaster  Thinline

→ telecaster thinline
```

Phase 0では複雑なモデル別名辞書は必須ではない。

---

## 7.3 Serial Number

照合時は以下を行う。

- 前後空白削除
- 大文字化
- 明らかな区切り記号を除去
- 不要なラベル除去

例：

```text
S/N: 729321
Serial #729321
729 321

→ 729321
```

ただし、意味のあるハイフンや接頭辞を持つメーカーもあるため、**元のserial_numberは必ず保存する**。

---

# 8. Web収集

## 8.1 Collector Interface

サイトごとの差異を吸収するため、Collectorを分離する。

概念例：

```python
class Collector:
    def discover_listing_urls(self) -> list[str]:
        ...

    def fetch_listing(self, url: str) -> str:
        ...

    def parse_listing(self, html: str, url: str) -> dict:
        ...
```

サイト追加時はCollectorを1つ追加するだけで済む構造を目指す。

---

## 8.2 クロール制御

Phase 0では以下を必須とする。

- User-Agent明示
- リクエスト間隔
- タイムアウト
- 最大取得ページ数
- 再試行上限
- エラーログ
- 同一URLの重複取得防止

デフォルトでは負荷を抑える。

例：

```text
delay: 2〜5秒
max_pages: 100
timeout: 20秒
retry: 2回
```

値は対象サイトに応じて調整する。

---

# 9. 情報抽出

1商品ページから最低限以下を抽出する。

```text
manufacturer
model
serial_number
seller
source_url
observed_at
title
raw_text
```

---

## 9.1 Manufacturer抽出

優先順位：

1. 構造化データ
2. 商品属性
3. タイトル
4. 本文

---

## 9.2 Model抽出

優先順位：

1. 構造化データ
2. 商品属性
3. タイトル
4. 本文

---

## 9.3 Seller抽出

優先順位：

1. 出品者フィールド
2. 店舗名フィールド
3. ページメタ情報

---

# 10. シリアル番号抽出

Phase 0の重要検証項目。

## 10.1 基本方式

以下を組み合わせる。

```text
正規表現
+
文脈キーワード
+
メーカー別ルール
```

候補キーワード例：

```text
Serial
Serial Number
Serial #
S/N
SN
シリアル
シリアルナンバー
製造番号
```

---

## 10.2 Candidate方式

本文中で直接1つに決めず、一度候補を生成する。

例：

```text
Candidate 1
729321
context:
"Serial number 729321"

Candidate 2
1377612
context:
"pot code 1377612"
```

その後、文脈から評価する。

---

## 10.3 Confidence

serial_numberにはconfidenceを付ける。

例：

```text
1.00
明示的なSerialフィールド

0.90
"Serial #xxxx" の直後

0.70
メーカー形式に一致 + 周辺文脈あり

0.40
形式のみ一致

0.00
抽出不能
```

Phase 0では、たとえば `0.70以上` を自動採用候補とする。

閾値はコード内に固定せず設定値とする。

---

## 10.4 誤抽出防止

以下の文脈にある数値をSN候補から除外・減点する。

- pot
- potentiometer
- neck date
- pickup
- patent
- price
- item number
- SKU
- weight
- year
- phone

---

# 11. 同一個体判定

Phase 0では判定を単純化する。

原則：

```text
normalized_manufacturer
+
normalized_model
+
normalized_serial
```

が一致した場合のみ、自動で同一Individualとして扱う。

---

## 11.1 Phase 0でしないこと

以下は自動マージ条件に使用しない。

- 写真
- 木目
- 傷
- 地域
- 出品者
- 価格
- カラー
- 年式推定
- AI類似判定

これらは将来の拡張項目とする。

---

## 11.2 Serial不明の場合

serial_numberが取得できない場合は、

**Observationとして保存してもよいが、自動Individualマージは行わない。**

Phase 0では、SNなしObservationを無理に同定しない。

---

# 12. Observation登録処理

登録処理は以下。

```text
商品ページ解析
    ↓
Observation生成
    ↓
serialあり？
    ↓ YES
既存Individual検索
    ↓
manufacturer + model + serial一致？
    ↓ YES
既存Individualへ紐付け
    ↓ NO
新規Individual作成
```

SNなしの場合：

```text
Observation保存
individual_id = NULL
```

または暫定Individualを作成してもよいが、Phase 0ではNULL推奨。

---

# 13. URL重複防止

同じページを毎回新Observationとして保存しない。

最低限、

```text
source_site + source_url
```

に一意制約または重複チェックを設ける。

ただし将来的には同一URLの内容変更をObservationとして扱う可能性があるため、Phase 0では仕様コメントを残す。

---

# 14. CLI仕様

Phase 0ではGUIよりCLIを優先する。

最低限以下を実装する。

---

## 14.1 DB初期化

```bash
ygc init-db
```

---

## 14.2 クロール

```bash
ygc crawl --site target --limit 100
```

---

## 14.3 個体一覧

```bash
ygc individuals
```

出力例：

```text
ID  Maker   Model                  Serial   Observations
1   Fender  Telecaster Thinline   729321   3
2   Gibson  Les Paul Standard     9-1234   2
```

---

## 14.4 Individual詳細

```bash
ygc show 1
```

出力例：

```text
Individual #1

Fender
Telecaster Thinline
Serial: 729321

Chronicle

2018-04-21  Shop A
2023-09-12  Auction B
2026-09-23  Dealer C
```

---

## 14.5 統計

```bash
ygc stats
```

例：

```text
Fetched pages: 100
Observations: 93
Serial extracted: 61
Serial extraction rate: 65.6%

Individuals: 57
Individuals with 2+ observations: 4
```

---

# 15. ログ

最低限以下を記録する。

```text
crawl start
crawl end
URL
HTTP status
parse success
parse failure
serial candidates
selected serial
confidence
individual matched
individual created
observation created
error
```

ログはローカルファイルへ保存する。

例：

```text
logs/ygc.log
```

---

# 16. テスト

## 16.1 Unit Test

最低限以下をテストする。

### Serial Extraction

- Serial明記
- S/N表記
- SN表記
- Pot Code混在
- 年式混在
- 複数数字混在
- SNなし

---

### Normalization

- 大文字小文字
- 空白
- 記号
- メーカー表記揺れ

---

### Matching

同じ：

```text
Fender
Telecaster Thinline
729321
```

が2回登録された場合、Individualが1件、Observationが2件になること。

---

## 16.2 Fixture

実際のHTMLを毎回ネット取得してテストしない。

取得済みHTMLを、

```text
tests/fixtures/
```

に保存し、抽出テストに利用する。

---

# 17. Phase 0 検証用サンプル数

最初の目標：

```text
100商品ページ
```

を目安とする。

100件取得できたら、まず結果を分析する。

いきなり数万件クロールしない。

---

# 18. Phase 0 KPI

以下を自動集計する。

## 18.1 Crawl Success Rate

```text
正常取得ページ / 発見ページ
```

---

## 18.2 Parse Success Rate

```text
正常解析 / 正常取得ページ
```

---

## 18.3 Serial Extraction Rate

```text
SN取得Observation / 全Observation
```

---

## 18.4 Manufacturer Extraction Rate

---

## 18.5 Model Extraction Rate

---

## 18.6 Seller Extraction Rate

---

## 18.7 Individual Count

生成されたIndividual数。

---

## 18.8 Repeat Observation Count

2件以上のObservationを持つIndividual数。

これがPhase 0で特に重要。

---

## 18.9 False Serial Rate

100件程度について人間が確認し、

```text
正しいSN
誤ったSN
SN不明
```

を評価する。

---

# 19. Phase 0 成功条件

Phase 0は以下を満たした時点で一旦完了とする。

### 必須

- 1サイトから100件程度取得可能
- SQLiteへ保存可能
- Manufacturer抽出可能
- Model抽出可能
- Serial抽出可能
- Seller抽出可能
- Observation生成可能
- Individual生成可能
- 同一 `Maker + Model + Serial` の再発見を統合可能
- CLIからChronicle表示可能
- 基本統計を表示可能
- Unit Testが存在する

---

### 評価対象

以下は成功必須条件ではなく、次Phase判断材料とする。

- SN取得率
- SN誤抽出率
- 同一個体再発見率
- サイト情報品質
- Chronicleとしての面白さ

---

# 20. Phase 0 完了後の判断

Phase 0完了時に以下をレポートする。

```text
取得ページ数
Observation数
Individual数

SN取得率
SN誤抽出率

2回以上観測されたIndividual数
最大Observation数

代表的なChronicle例
抽出失敗例
誤判定例

次に改善すべき項目
```

この結果を見て、

```text
同一サイトで継続収集
別サイト追加
抽出改善
モデル正規化改善
SNルール改善
```

のどれを優先するか決める。

---

# 21. 将来拡張を意識する箇所

Phase 0では実装しないが、以下を後から追加できる構造にしておく。

```text
複数Collector
画像解析
LLM抽出
Claim
Evidence
Attestation
Merge Candidate
User
Dealer
Repair Shop
価格履歴
地域履歴
写真履歴
全文検索
Web UI
API
PostgreSQL
```

ただし、**将来拡張のために現在のコードを過剰設計しない**。

---

# 22. Codexへの実装指示

Codexに本書を渡す場合は、企画書と合わせて以下の指示を使用する。

---

## 推奨プロンプト

```text
添付の

- Your Guitar Chronicle 企画書（改訂案）
- Your Guitar Chronicle Phase 0 実装仕様書

を読んでください。

今回はPhase 0のみを実装します。

最初に既存リポジトリの状態を確認し、実装を開始する前に、

1. 採用する対象サイト
2. ディレクトリ構成
3. DBスキーマ
4. Collector設計
5. Serial抽出方式
6. テスト方針

を短く提示してください。

その後、Phase 0実装仕様書に従って実装してください。

重要事項：

- 最初は1サイトのみ対応してください。
- 最大100商品程度の検証を想定してください。
- Phase 1以降の機能は実装しないでください。
- User / Claim / Login / Server公開は不要です。
- 画像OCRは不要です。
- 同一個体自動判定は maker + model + serial の一致だけに限定してください。
- Webサイト側の利用規約やrobots.txtに反する回避処理は実装しないでください。
- 取得できないサイトの場合は、強引に突破せず理由を報告してください。
- 可能な限りFixtureを使った再現可能なテストを作成してください。
- 実装後はpytestを実行してください。
- 実装後にPhase 0 KPIを確認できるCLIを用意してください。
- READMEにセットアップ方法と実行例を記載してください。

不明点があっても、Phase 0の目的を超える機能を勝手に追加しないでください。
判断が必要な場合は、最も単純な実装を選択してください。
```

---

# 23. 開発原則

Phase 0では次の順序を守る。

```text
動く最小パイプライン
        ↓
取得結果を見る
        ↓
問題を測る
        ↓
必要な部分だけ改善
```

最初から完全なクローラー、完全なシリアル識別、完全な個体同定を目指さない。

本Phaseの最大の目的は、

> **Web上の公開情報を継続的に取得することで、本当に個体単位のChronicleが自然に形成されるか**

を検証することである。
