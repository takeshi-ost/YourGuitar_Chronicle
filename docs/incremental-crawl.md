# 手動分割クロール（試作）

Browser Console の Incremental Crawl は、製造年の下限・上限と Electric / Acoustic の分野を指定して `Advance` を押すたびに進む。従来の任意検索 Batch Crawl は独立して残る。

- 条件ごとに SQLite にページリンクと未処理の一覧を保存する。1クリックで未処理の一覧最大5件、詳細最大5件、既存Listingの公開確認最大2件を処理する。次のクリックとサーバー再起動後は続きから再開する。失敗した詳細の位置は進めない。
- 検索には製造年の `year_min` / `year_max` と分野に対応する検索語を使う。詳細の構造化 `year` とカテゴリも確認し、年やカテゴリを特定できないものは登録しない。Reverb API のカテゴリ検索パラメータは確認できていないため、この方式はカテゴリ全件の網羅を保証しない。
- API呼び出しを直列に行い、少なくとも1秒の間隔を置く。429と一時的な5xxは既存のバックオフで再試行し、エラーではカーソルを進めない。API由来のページリンクは設定済みAPIホストに限定する。
- 既存のReverb Observationは、初回または前回の公開確認から7日以上経過したものから1クリックにつき最大2件を確認する。404/410を初めて確認したときは日時だけ記録し、24時間以上後の再確認でも404/410だった場合に公開停止と記録する。それ以外のHTTPエラーは公開停止と扱わない。公開停止後の再確認は30日以上間隔を空ける。
- 個体に紐付いたObservationにはAutomationによるClaimを作る。現在のOwner・LocationがそのReverb Listingだけに基づく場合はOwnership / Release ClaimによってUnknownにする。独立したユーザーOwnerや別のListingが根拠の場合はEvent Claimのみ作り、Ownerは変えない。個体に紐付かないObservationにはClaimを作れないため、公開確認結果だけ保存する。
- 新しいListing IDから同一個体を再発見した場合、既存のListing Claimを維持してAutomationによるAcquire Claimを作る。現OwnerがYGCユーザーなら既存Owner VerificationのUnverified状態とし、Positiveになるまでスナップショットを変えない。
- ページ末尾に達した後も公開確認は `Advance` で進められる。新規Listingを先頭から探すときは `Restart Scan` を使う。既存Observation・Claimは消えない。自動定期実行と実際のReverb APIトークンを用いた動作検証は未実施。
