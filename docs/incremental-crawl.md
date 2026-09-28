# Reverb収集とBrowser Consoleの集計

目的は指定した範囲から**メーカーと有効なシリアル番号を判別できるギター**を抽出し、個体を新規登録するか、既存個体に掲載来歴を追加すること。Vintage判定やObservation総数を登録条件・成果指標にしない。検索語とAPIの順位のため、検索結果が全掲載を網羅する保証はない。

## 手動実行の2つの入口

| 入口 | 範囲指定 | 実行 |
| --- | --- | --- |
| Batch Crawl | 1行1クエリ、件数など | 任意検索を実行 |
| Incremental Crawl | electric / acoustic、製造年の下限・上限 | 1クリックごとに保存済みカーソルから続ける。1回に一覧最大2000件、該当候補の詳細は件数上限なし |

両入口は詳細保存・メーカー／シリアル抽出・DBへの登録パイプラインを共用する。既知のListing ID、キャッシュ中の見送りなどを一覧段階で除外する。分野や年を判別できない・範囲外の候補は見送り、必要な詳細を取得したら**判定より先に**JSONと取得日時を `crawl_detail_cache` に保存する。詳細取得失敗で成功済み詳細を上書きしない。

条件を満たしてもメーカーまたは有効なシリアルがなければIndividual / Claim / Observationは新設しない。見送り理由とListing IDを期限付きで保存する（identity不足は7日、範囲外は30日）。有効候補は `crawl_candidates` に永続保存し、まとめて個体照合する。候補の段階保存と外部Listing IDの再確認により、停止からの再実行で重複Claimを防ぐ。モデルの矛盾・不明など曖昧な一致は `review` に置き、自動統合しない。管理画面に確認待ち候補の**一覧はあるが承認操作は未実装**。

「保存済み詳細を再判定」はキャッシュ済みJSONを選択中の分野と製造年で再抽出・照合する。Reverbへの通信・APIトークンは使わない。以前に詳細を保存していなかったListingの情報は再現できない。

Incremental Crawlは一覧を最大2000件処理し、既存Listingの公開状態を1回最大5件確認する。API要求は直列で最低0.5秒間隔。404 / 410を24時間以上離して2度確認した場合にだけ、Reverb掲載だけが現Owner / Locationの根拠ならAutomationのRelease ClaimによりUnknownへ戻す。他のClaimに根拠があれば維持する。定期実行は未実装。

## 進捗・ログと数値の意味

一覧スクリーニング、詳細取得、シリアル候補抽出、個体照合、Claim付き登録の段階を実行中に表示し、`crawl_runs` に段階別の件数と終了／失敗を残す。画面では対象範囲の最新20回を表示し、古いログはDBに残る。

| Browser Consoleの数値 | 現行定義 |
| --- | --- |
| Registered Guitars | DBのIndividual総数（手動登録と外部登録を含む） |
| Serial Listings | シリアルを持つ個体の有効な外部Listing証跡のユニーク件数。Listing / Acquireの由来を数え、同一source + Listing IDは重複除外。Unverifiedも含む |
| Repeated | 同一の正規化メーカーとシリアルを持つ**異なるIndividual群**の数。複数Listingを持つ一個体の数ではない |
| Unverified Acquire | 承認すると現在の所有者が変わり得る、有効な承認待ちAcquire Claim。承認前後のOwnerをSnapshot評価して判定 |
| New Discovery | 最終ClaimまたはObservationによる更新が新しい個体を最大200件表示。Crawlの新規登録件数とは別 |

データの意味・判定の管理操作は [CLAIM_CENTERED_ARCHITECTURE.md](CLAIM_CENTERED_ARCHITECTURE.md) と [console-claim-administration.md](console-claim-administration.md)。実Reverbトークンを使った現行パイプラインの総合検証、取りこぼし・誤照合の標本評価は引き続き必要。
