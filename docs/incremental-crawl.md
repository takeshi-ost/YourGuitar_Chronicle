# Reverb収集とBrowser Consoleの集計

目的は指定した範囲から**メーカーと有効なシリアル番号を判別できるギター**を抽出し、個体を新規登録するか、既存個体に掲載来歴を追加すること。Vintage判定やObservation総数を登録条件・成果指標にしない。検索語とAPIの順位のため、検索結果が全掲載を網羅する保証はない。

個体に登録する外部掲載はClaimとEvidenceを保存し、旧 `observations` 行は新設しない。進捗の `observations_created` / `new_observations` は互換名で、新たに保存した掲載の件数を示す。既知Listingと公開状態確認はEvidenceを優先し、未移行・個体未登録の旧記録も参照する。

保存処理へ直接渡された入力が個体識別条件を満たさない場合は、入力全体を `crawl_unregistered_records` に期限なしで保持し、Individual・Claimは作成しない。通常の増分クロールにおける期限付きの見送り記録・詳細キャッシュとは別の保存先である。

## 手動実行の2つの入口

| 入口 | 範囲指定 | 実行 |
| --- | --- | --- |
| Manual Crawl | ボタンからモーダルで1行1クエリ、件数など | 任意検索を実行 |
| Incremental Crawl | Electric + Acoustic Guitars、製造年の下限・上限 | 1クリックごとに保存済みカーソルから続ける。1回に一覧最大2000件、該当候補の詳細は件数上限なし |

両入口は詳細保存・メーカー／シリアル抽出・DBへの登録パイプラインを共用する。既知のListing ID、キャッシュ中の見送りなどを一覧段階で除外する。分野や年を判別できない・範囲外の候補は見送り、必要な詳細を取得したら**判定より先に**JSONと取得日時を `crawl_detail_cache` に保存する。詳細取得失敗で成功済み詳細を上書きしない。

新規個体のListing Claimを作る際は、その掲載IDの保存済みDetailから項目名が明示された短い仕様値だけを抽出し、得られた場合だけAutomationのPositiveなSpecification Claimを同じトランザクションで作る。FinishはListingの値と重複するため含めない。状態説明、文章、装飾記号は捨て、Reverb IDをSpecification専用の出典記録に残す。既存個体の再掲載AcquireではSpecificationを自動生成しない。Browser Consoleの「Specificationを整理・追加」は旧自動生成値の整理と、現在ユーザーOwnerがいない既存個体の手動バックフィル用。

条件を満たしてもメーカーまたは有効なシリアルがなければIndividual / Claim / Observationは新設しない。見送り理由とListing IDを期限付きで保存する（identity不足は7日、範囲外は30日）。有効候補は `crawl_candidates` に永続保存し、まとめて個体照合する。候補の段階保存と外部Listing IDの再確認により、停止からの再実行で重複Claimを防ぐ。モデルの矛盾・不明など曖昧な一致は `review` に置き、自動統合しない。管理画面に確認待ち候補の**一覧はあるが承認操作は未実装**。

「保存済み詳細を再判定」はキャッシュ済みJSONを選択中の分野と製造年で再抽出・照合する。Reverbへの通信・APIトークンは使わない。以前に詳細を保存していなかったListingの情報は再現できない。

Incremental Crawlは一覧を最大2000件処理し、既存Listingの公開状態を1回最大5件確認する。API要求は直列で最低0.5秒間隔。404 / 410を24時間以上離して2度確認した場合に、掲載IDごとの確認結果を `crawl_listing_checks` に保存する。その掲載だけが現在の非ユーザーOwner / Locationの根拠なら、Automation専用のOwnership / Lost ClaimによりUnknownへ戻す。ユーザーが所有中、または別の掲載が現在値の根拠ならClaimを追加しない。確認ログはどちらの場合も保持する。旧版で作られた掲載終了Event ClaimやAutomation Release Claimは自動削除・改変しない。Auto CrawlはOperationsのReverbチェックとWeb Crawlの時間設定で制御する。

現行Reverb取り込みでは、掲載のseller名を非ユーザーの `current_owner_name` に、seller名があれば暫定的に `current_owner_type=shop` に反映している。これは売主を実際の所有者と確認した記録ではない。`current_owner_user_id=NULL` にはseller表示中の個体とUnknownの両方が含まれる。掲載終了によるLostは所有放棄を意味しない。ユーザーが作るIncident / LostとはClaim種別と作成権限が異なる。

## 進捗・ログと数値の意味

一覧スクリーニング、詳細取得、シリアル候補抽出、個体照合、Claim付き登録の段階を実行中に表示し、`crawl_runs` に段階別の件数と終了／失敗を残す。画面のCrawl Run Logでは分野・製造年にかかわらず全体の最新20回を表示し、古いログはDBに残る。Manual Crawl、詳細キャッシュ再処理、Listing backfillの履歴も同じ欄へ集約する。

| Browser Consoleの数値 | 現行定義 |
| --- | --- |
| Registered Guitars | DBのIndividual総数（手動登録と外部登録を含む） |
| Serial Listings | シリアルを持つ個体の有効な外部Listing証跡のユニーク件数。Listing / Acquireの由来を数え、同一source + Listing IDは重複除外。Unverifiedも含む |
| Repeated | 同一の正規化メーカーとシリアルを持つ**異なるIndividual群**の数。複数Listingを持つ一個体の数ではない |
| Unverified Acquire | 承認すると現在の所有者が変わり得る、有効な承認待ちAcquire Claim。承認前後のOwnerをSnapshot評価して判定 |
| New Discovery | 有効かつBANされていない作成者のClaimの作成日時、またはその掲載Evidenceの取得日時が新しい個体を最大200件表示（未移行掲載は旧記録を参照）。Crawlの新規登録件数とは別 |

データの意味・判定の管理操作は [CLAIM_CENTERED_ARCHITECTURE.md](CLAIM_CENTERED_ARCHITECTURE.md) と [console-claim-administration.md](console-claim-administration.md)。実Reverbトークンを使った現行パイプラインの総合検証、取りこぼし・誤照合の標本評価は引き続き必要。


## 対象カテゴリとクロール前バックアップ

クロール対象はElectric Guitars／Acoustic Guitarsのみ。All Guitarsは入力UI・新規実行API・CLIから除く。過去のallの履歴は削除しない。保存済みAuto Crawlがallの場合は自動実行を保留し、Electric + Acoustic Guitarsの設定を保存する。既存のelectric／acoustic設定は両方を対象とする設定へ切り替え、ON／OFF・製造年・実行間隔・次回実行時刻を保持する。Batchも登録時に明示カテゴリを確認し、不明カテゴリ・ベース・アンプ・パーツを登録しない。過去の混入レコードは自動削除しない。

Browser Consoleの手動・自動クロール、保存済み詳細の再処理、CLIのcrawl／crawl-stepは開始前にChronicle DBとmediaのZIPを保存する。バックアップ失敗時は実行を止める。保持世代数はGuitar DBのCrawl backupsで1〜100件（初期10件）を指定し、最新の保存成功後に最古から削除する。保持数変更は次回バックアップで適用。保存先はYGC_DATA_DIR/crawl_backups、保持設定はoperations.sqliteでDB復元から独立する。

保存済みバックアップのRestoreは管理トークン必須。メンテナンス（閲覧のみ／全面停止）を有効にし、実行中ジョブの終了を待つ。既存のZIP検証・DB／media復元・失敗時ロールバックを使用し、復元前にも現在状態のバックアップを保存する。Operations設定と保存済みバックアップ群は復元で置き換えない。既存復元の512 MB上限を超えるZIPは自動保存を失敗させ、クロールを開始しない。

### Electric／Acousticの一括収集

Crawl前保存はBackupsのChronicle対象に記録され、手動・定期・復元前保存と保持枠を共有する。OperationsとAuthentication実験はCrawl前には保存せず、個別の定期保存または手動保存を使う。詳細は[UI_STRUCTURE.md](UI_STRUCTURE.md)のBackupsの一元管理を参照。

Browser ConsoleのIncremental CrawlとAuto Crawlは、Electric + Acoustic Guitarsを一度に扱う。内部ではelectric guitar／acoustic guitarを順に検索し、それぞれ最大1,000件（合計最大2,000件）を処理する。両カテゴリの候補をまとめて照合し、Listing IDの重複を排除する。掲載状態の確認は一括実行につき最大5件、開始前バックアップと実行ログは各1回。カテゴリごとの検索位置を永続化し、途中停止後も続きから再開する。Restart Scanの画面ボタンは整理時に削除。互換APIのrestartは両方の検索位置を戻す。既存のカテゴリ別の検索位置は引き継ぐ。保存済み詳細の再判定も両カテゴリが対象。API／CLIのelectric・acoustic指定は互換のため維持し、CLI crawl-stepの既定値はelectric_acousticとする。
