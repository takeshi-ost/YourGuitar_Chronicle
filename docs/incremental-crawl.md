# Reverb クロール（手動実行）

目的は指定範囲の Listing からメーカーと有効なシリアル番号を持つギターを探し、新規個体または既存個体の来歴として Claim を記録すること。Vintage 判定や Observation 件数は登録条件・成果指標ではない。

- Batch Crawl は任意の検索語、Incremental Crawl は分野と製造年範囲を入口にする。詳細の候補選別、シリアル抽出、既存個体との照合は共通。検索語・APIの検索順位のため、検索結果が分野の全件を網羅するとは保証しない。
- 両Crawlとも詳細取得成功時、判定前にレスポンスの内容と取得日時を `crawl_detail_cache` に保存する。年・分野不明、メーカー・シリアル不明で見送る詳細も残す。取得失敗時の一覧データで詳細キャッシュを上書きしない。
- Browser Console の「保存済み詳細を再判定」は現在指定した分野・年範囲でキャッシュを再抽出・照合する。ネットワークアクセスもトークンも不要。元の取得日時を確認日時として使い、登録済みListingのClaimを二重作成しない。見送り期限中でも再判定できる。新方式導入前に保存されなかった詳細は復元できない。
- 詳細にメーカーか有効なシリアルがない場合は個体・Observation・Claim を作らない。Listing ID と見送り理由を7日間キャッシュし、説明文の更新に備えて再確認できるようにする。範囲外は30日間キャッシュする。既存の番号なし Observation は削除しない。
- 有効な候補は SQLite の `crawl_candidates` に保存してからページカーソルを進める。取得区間の末尾でまとめて既存個体を照合する。途中停止後も未照合候補を再処理でき、Claim の重複は Listing ID の確認で防ぐ。
- メーカーとシリアルが一致し、モデルも矛盾しない場合は既存個体の Acquire Claim にする。同じ番号にモデルの矛盾や不明な既存モデルがある場合、また旧形式の個体に有効な Listing Claim がない場合は `review` として候補に保持し、自動統合しない。現所有者がユーザーなら既存Owner Verificationの Unverified を使う。
- Incremental Crawl は1回につき一覧最大2000件をページリンクに沿って走査する。詳細件数と一覧ページ数には独立した上限を設けず、候補がすべて該当する場合は最大2000件の詳細を取得する。既存Listing公開確認は最大5件。APIリクエストは直列で最低0.5秒空ける。429と一時的な5xxには既存Collectorの再試行を使う。カーソルは各候補ごとに保存される。
- 公開確認は404/410を24時間以上離して2度確認してから行う。ReverbのListingだけが現Ownerの根拠ならAutomationのRelease ClaimでUnknownにする。他の根拠があればOwnerは維持する。
- 成果は新規個体数、既存個体への来歴追加数、確認待ち数で表示する。実際のReverb APIトークンによる今回の変更後の検証と確認待ち候補の手動承認画面は未実施。

## Browser Console の集計

- Registered Guitars: DBの個体総数。手動登録も含む。
- Serial Listings: シリアルを持つ個体に紐付いた外部Listingのユニーク数（source_site / source_listing_id）。有効なListingまたはAcquire Claimに結び付くものを数え、ユーザーの初期登録は除外する。所有者確認の結果とは別の掲載証跡件数なので、Unverifiedも含む。
- Repeated: 上記の外部Listingを2件以上持つ個体数。再出品をAcquireで記録する現在の仕様に対応する。
- Guitar DB ManagementのUnverified Acquire: 有効なOwnership / Acquire Claimのうちverification_statusがunverifiedの総数と一覧。100件ずつ表示し、行から対象個体のProduct Detailを開く。承認済み・無効化済みは表示しない。
