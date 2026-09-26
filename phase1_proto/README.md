# Your Guitar Chronicle — Phase 1 (Reverb API)

ローカルPC上でReverb公式APIからListingsを読み取り、`manufacturer / model / serial / seller` をObservationとしてSQLiteへ保存し、同一 `maker + model + serial` を同じIndividualに関連付けるPoCです。

## 重要
この実装はReverbのHTMLをスクレイピングしません。Reverb公式APIのみを利用します。

## 必要環境
- Python 3.12以上
- Reverbアカウント
- Reverb Personal Access Token

macOS(Homebrew):
```bash
brew install python@3.12
python3.12 --version
```

## Token
Reverbの My Profile → API & Integrations → Generate New Token からPersonal Access Tokenを作成してください。このPoCは読み取りのみなので、利用可能なscopeの中で `public` / `read` 系の必要最小限だけを選び、write/orders系は付けないでください。

macOS/Linux:
```bash
export REVERB_API_TOKEN='YOUR_TOKEN_HERE'
```
Windows PowerShell:
```powershell
$env:REVERB_API_TOKEN='YOUR_TOKEN_HERE'
```
TokenはChatやGitHubへ貼らないでください。

## セットアップ
```bash
cd your-guitar-chronicle-phase1
python3.12 -m venv .venv
source .venv/bin/activate     # macOS/Linux
# .venv\Scripts\Activate.ps1  # Windows PowerShell
python -m pip install --upgrade pip
pip install -e ".[dev]"
pytest -q
```

## DB初期化
```bash
ygc init-db
```

## API疎通
```bash
ygc reverb-probe --query "vintage guitar"
```
401ならToken/scopeを確認してください。400/422で`query`が拒否された場合は、Reverb側の現在の検索パラメータ仕様に合わせて `src/ygc/collectors/reverb.py` のparamsだけ調整してください。

## 最初の10件
```bash
ygc crawl --query "vintage guitar" --limit 10
ygc stats
ygc individuals
```
問題なければ:
```bash
ygc crawl --query "vintage guitar" --limit 100
ygc stats
```

## Chronicle表示
```bash
ygc individuals
ygc show 1
```

## 主なKPI
`ygc stats` で次を確認します。
- observations
- serial_observations
- serial_extraction_rate
- individuals
- repeated_individuals
- max_observations_per_individual

最重要は `repeated_individuals` です。

## Serial抽出
現在は `Serial number`, `Serial #`, `S/N:`, `SN:` を優先するルールベースPoCです。メーカー別SN体系や画像OCR、LLM判定はまだ入れていません。

## API差異への対応
`reverb_adapter.py` は `make / brand / manufacturer`, `model`, `shop.name / seller.name`, `description / body`, `published_at / created_at / listed_at` を順に参照します。`ygc reverb-probe` で実レスポンスを確認し、必要ならAdapterのみ修正できる構造です。

## 環境変数
- REVERB_API_TOKEN
- REVERB_API_BASE
- YGC_DB_PATH
- YGC_DATA_DIR
- YGC_LOG_DIR
- YGC_REQUEST_TIMEOUT
- YGC_REQUEST_DELAY
- YGC_SERIAL_CONFIDENCE_THRESHOLD

例:
```bash
export YGC_REQUEST_DELAY=2.0
export YGC_SERIAL_CONFIDENCE_THRESHOLD=0.80
```

## Phase 1後の確認
100件取得後に、SN取得率・誤抽出率・Make/Model/Seller取得率・同一個体再発見件数・Timelineとして面白い個体が生まれたかを確認し、次にReverb継続、SN抽出改善、別Collector追加のどれを優先するか決めます。
