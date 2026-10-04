# GCP 移行のための境界（現在はローカル試作）

この文書は将来の Cloud Run + Cloud SQL (PostgreSQL) + Identity Platform + Cloud Scheduler / Cloud Run Jobs への移行契約を示す。現行の一般WebUIはローカル試作。独立した[Cloud Run認証画面](CLOUD_RUN_ACCOUNT_STAGING.md)の基本認証試験は完了し、[Accounts同期Job](ACCOUNT_PROJECTION_JOB.md)を配置済み。[クラウドConsole](CLOUD_BROWSER_CONSOLE.md)の管理者Operationsと[Cloud Storageの接続基盤](CLOUD_STORAGE.md)を追加した。[本人アカウント画像](CLOUD_ACCOUNT_AVATAR.md)は保存／取得／参照解除を接続済み。一般WebUIのPostgreSQL接続、コンテンツ画像のアップロード／配信、Crawl等のクラウド定期実行は残る。実装ブランチに追加した接続・初期スキーマ基盤の範囲は[PostgreSQL初期化](POSTGRES_BOOTSTRAP.md)を参照。ローカルAuto Crawlと定期バックアップは実装済み。`ygc.platform_boundaries` は接続前後の型とローカル実装を定義し、未接続のクラウド側は明示的にエラーにする。

| 責務 | 現在 | 将来の差し替え点 |
| --- | --- | --- |
| HTTP 実行 | FastAPI をローカルで起動 | Cloud Run に配置し、起動時に本番アダプターを必須とする |
| 利用者の本人確認 | 標準の `local_dummy` はローカルセッションとアカウントを照合する。`prototype` は未検証IDの互換モード | Identity Platform の ID token をサーバーで検証し、発行者と subject を `users.id` に対応付ける。クライアント指定 ID を本人確認に使用しない |
| 永続データ | `local_repository` が SQLite `Repository` を返す | PostgreSQL リポジトリと移行スキーマへ交換する。Claim とその承認・履歴の意味を保持する |
| クロール | `LocalCrawlRunner` が既存の `advance_program` を１ステップ実行する | Scheduler が権限付きで Cloud Run Job を起動し、ジョブが永続カーソルから１ステップ実行する |
| 画像等のファイル | ローカルファイル | 永続オブジェクトストレージへ移し、DB には参照を保存する |

## 認証境界

標準の `local_dummy` はloopback専用のテストユーザー選択からサーバー発行セッションを作り、操作IDを照合する。ただしメール・パスワードによる実際の本人確認ではなく、このローカル認証でIdentity Platformの署名JWTを検証することはない。クラウド用の検証部品は[別経路](IDENTITY_PLATFORM_VERIFICATION.md)で実装済み。互換 `prototype` では `viewer_id` 等が未検証の申告IDとなる。公開前には全APIをIdentity Platformの検証済み主体に接続し、管理者権限・画像等の直接参照を含めて認可を検証する。アカウントの固定UUID・認証対応付けは後述のアカウントDBを正とし、コンテンツ内usersは参照用の投影として扱う。

将来の受け渡し順序は、クライアントが Identity Platform で取得した ID token → HTTPS リクエストの Bearer token → サーバーが署名・発行者・対象・有効期限等を検証 → `(identity_provider, identity_subject)` で `users.id` を解決 → `verified=True` のコンテキストを業務処理へ渡す、となる。`users` に nullable な対応付け列と一意インデックスを用意した。既存利用者との対応付け・移行時の重複解消は後で明示的に行う。プロトタイプ ID や表示名から自動的に同一人物とみなさない。

## DB・ジョブ境界

SQLite 固有の SQL・マイグレーション・同時書き込み処理は PostgreSQL 向けに移植する必要がある。特に Claim の派生状態、クロールのカーソルとログ、重複防止を維持し、複数インスタンスで同じステップを同時処理しないよう DB のトランザクションとロックを設計する。Cloud SQL への接続管理と機密情報の保管も移行時に実装する。

ローカルの `ygc crawl-step --category electric_acoustic --year-min 1950 --year-max 1980` は既存の保存済みカーソルを使い、一度の呼び出しで１ステップだけ進める同期実行の入口である。ローカルWebではAuto Crawlを定期起動するが、クラウドジョブの実装ではない。将来は Cloud Scheduler が Cloud Run Job を起動し、Job 側がカテゴリーと製造年範囲を受け取って同じ業務処理を呼ぶ。手動実行と定期実行は `CrawlStep.origin` で区別できるが、実行の重複・再試行・失敗時再開は永続ストアで制御する。今の Web のバックグラウンドスレッドとメモリ内 `_jobs` は複数インスタンスや再起動をまたげないため、移行時にジョブ状態の保存先も交換する。

`K_SERVICE` / `CLOUD_RUN_JOB` が設定された環境、または `YGC_PLATFORM_TARGET` 等で未実装のバックエンドを指定した環境では、ローカル DB を開く前に `PlatformAdapterRequired` で停止する。クラウド上でローカル SQLite や未検証の利用者 ID をそのまま運用しないためのガードであり、デプロイ可能になったという意味ではない。

ローカル開発基盤の完了状況・残作業とデータ移行前の準備は[GCP移行前の整備状況](../development/GCP_PREPARATION_STATUS.md)を参照。

## 初回移行と公開前のDBリセット方針（2026-10-04）

GCP移行時はDBを新規初期化して試験を始める。現在のローカルDB・画像・旧Observationをクラウドへ引き継ぐことは初回移行の要件としない。ローカルの保存データを削除する指示ではなく、既存データの移送・全件比較・旧バックアップのクラウド復元を移行開始の必須条件から外す方針である。

公開前の試験中は数回のリセットを想定する。クラウド側には、最新スキーマの作成、最低限の管理者・試験データの投入、リセット後の整合確認を繰り返し実行できる手順を用意する。スキーマ更新と試験データの投入は分け、Crawlで再収集できるようカーソル・キャッシュ・重複判定状態もリセット範囲に含める。

| 操作範囲 | 方針・確認対象 |
| --- | --- |
| 初回GCP初期化 | 新しいDBと画像保存領域を用意する。ローカルの数値ID・UUID・認証対応を自動移送しない。管理者と試験ユーザーは明示的に準備する |
| コンテンツのみの再初期化 | 個体・Claim・根拠・申請・係争・通知・お気に入り・収集状態・関連画像を対象とする。Accountsと認証主体を維持し、ユーザー投影を再作成する。signature guitarなど削除個体への参照も解消する |
| アカウントを含む全試験データの再初期化 | Accounts・交流・同意・アカウント画像・認証対応・セッションまで対象とする別操作。認証サービス側の試験ユーザーを残すか削除するかも明示する。DBだけを空にして対応の不整合を残さない |
| 運用・実験状態 | 対象DBと連動するキュー・停止中回答・ジョブ・キャッシュを整理する。サービス設定・管理者の復旧経路・シークレットを維持するか再設定するか、操作ごとに明示する |

リセット中は書込・Crawl・GPT反映・定期ジョブを止める。リセット前に開始したジョブや遅延回答が新しいDBへ反映されない仕組み（試験世代の識別等）を設ける。画像・バックアップも世代と対象を区別し、旧世代のバックアップを初期化済みDBへ誤って復元しないようにする。

公開前の専用環境を対象とする明示的な管理手順として実装し、対象環境・範囲を確認して実行する。公開後の通常運用では全消去を前提にしない。リセットの実行手段は未実装であり、この方針の記録によって現在のDBや認証ユーザーを消去することはない。

既存データの移行監査は将来、ローカルDBや旧バックアップを取り込む必要が生じた場合に行う。新規DBでも、試験データによる所有権・認可・画像参照・独立復元の検証は必要。

## 移行前に確定すること

1. 更新／閲覧APIごとにGuest、本人、現在Owner、管理者の権限を表にし、ブラウザから届く `user_id` / `viewer_id` を本人証明にしない。プロフィールの直接API・画像配信も含めて検査する。
2. 新規DBに試験データを投入し、対立する所有Claim、再出品の同一個体判定、Merge後の再承認条件を検証する。既存データを取り込む場合のみ、移行前後のSnapshot比較を追加する。
3. DBと画像の初期化・試験データ投入・独立バックアップ／復元手順を準備する。初回は空のDBから始め、既存SQLiteの移送を必須としない。
4. 収集の途中停止・再実行・二重起動・429応答時の動作を標本検証する。管理画面の候補review一覧に承認操作はまだない。

## 移行時に残る作業

- Identity Platform のトークン検証と利用者対応付け、全エンドポイントの認可と管理権限の検証。Sign Inはダミーセッション、Create Accountはローカルアカウント・Profile・同意を保存するが、Google認証ユーザーは作成しない。
- PostgreSQL スキーマ・データ移行・接続プール・Claim の同時更新とカーソル排他。
- 画像の永続化とアクセス制御、Reverb API トークンやその他のシークレットの安全な管理。SQLiteのバックアップ/復元UIはCloud SQL運用手順へ置換する。
- Cloud Run Job の実装・ジョブ状態の永続化・Cloud Scheduler の認証付き起動と再試行設計。
- 実環境での統合テスト、移行後のローカル依存の撤去。

## GCP移行後の追加作業：Admin権限とAdmin Onlyモード

2026-10-03の方針として、ローカル試作への実装は見送り、GCP移行後に本人認証・認可を整備したうえで追加する。

- AdminはUser Type（user / shop / builder等）とは独立した権限として管理する。検証済みIdentity Platformの本人情報からユーザーと権限をサーバー側で解決し、画面のユーザー選択やクライアント指定IDだけでAdminとみなさない。
- メンテナンスモードに「Admin Only」を追加し、認証済みAdminだけが閲覧・編集できるようにする。Guestと一般ユーザーにはメンテナンス案内を表示する。Adminによる編集にも、既存の業務上の制約・管理者操作の監査を適用する。
- ページ表示だけでなく、直接API、画像・非公開Evidenceの取得にも同じアクセス制限を適用する。既存のEvidence閲覧権限を迂回するモードにしない。
- モードと権限を共有永続ストアで管理し、複数インスタンスでも同じ制限を適用する。モード切替・Admin権限の付与／解除を監査記録に残す。
- 認証済み管理者がモードを解除できる復旧経路を用意する。一般ユーザーによるID偽装、直接API・画像アクセス、権限解除後のアクセス、複数インスタンスへの反映を検証する。

## 調査：アカウントとコンテンツの分離・独立復元（2026-10-03）

以下はGoogle公式資料を確認した設計案。ローカルでのDB分離・ダミー認証・独立復元は末尾の手順で利用できる。この節は初期設計時の案であり、実装・接続の現在状態は[構築状況](GCP_STAGING_SETUP.md)と各移行文書を参照する。

### 確認したGCPの仕様

- Cloud Runの一般利用者認証にはIdentity Platformを利用でき、アプリ側でID tokenを検証する。一般利用者にCloud Run IAM権限を与える方式とは区別する。[Cloud Runの利用者認証](https://docs.cloud.google.com/run/docs/authenticating/end-users)
- サーバーで署名・有効期限・発行者・対象プロジェクトを検証し、検証済みuidを取り出す。通常のトークン検証だけでは失効確認をしないため、失効確認を明示的に設計する。[ID token検証](https://firebase.google.com/docs/auth/admin/verify-id-tokens)、[セッション失効](https://firebase.google.com/docs/auth/admin/manage-sessions)
- 複数のログイン手段を同じIdentity Platformアカウントへリンクできる。ログイン手段のgoogle.com等をサービス内の人のIDとして扱わない。[アカウントリンク](https://docs.cloud.google.com/identity-platform/docs/link-accounts)
- tenantを使う場合はユーザー集合がtenantごとに分かれる。対応付けではプロジェクト／発行者、tenant（未使用なら明示的な空値）、uidを含める。tenant導入は現時点の必須条件ではない。[tenant管理](https://docs.cloud.google.com/identity-platform/docs/multi-tenancy-managing-tenants)
- Admin等のCustom ClaimsはID tokenの更新時に反映される。即時のBAN・権限解除を古いtokenだけで判定しない。[Custom Claims](https://firebase.google.com/docs/auth/admin/custom-claims)
- Identity Platformのユーザーimportは既存uidとの衝突時に既存ユーザーを置換する。コンテンツ復元に認証ユーザーのimportを組み合わせない。[ユーザー移行](https://docs.cloud.google.com/identity-platform/docs/migrating-users)
- Cloud SQLの通常復元はインスタンスのDB群・設定等を対象とし、PITRは新しいインスタンスを作る。同一インスタンス内でDB名を分けても通常復元の単位が別になるわけではない。[復元の概要](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/restore)、[PITR](https://docs.cloud.google.com/sql/docs/postgres/backup-recovery/pitr)
- PostgreSQLのSQL exportはDBを指定できる。DB別復旧には論理export/import、または別インスタンスへ復旧して必要なDBを取り出す手順を使う。[SQL export/import](https://docs.cloud.google.com/sql/docs/postgres/import-export/import-export-sql)

### このプロジェクトへの設計案

| 層 | 正として保持する情報 | コンテンツ復元時 |
| --- | --- | --- |
| Identity Platform | ログイン資格情報・認証uid・認証アカウントの状態 | 巻き戻さない |
| アカウントDB（新設案） | 永続app_user_id、認証uidとの対応、プロフィール、公開設定、User Type、BAN・退会状態、Admin権限 | 巻き戻さない |
| コンテンツDB（現Chronicle） | ギター・Claim・所有関係・申請・係争、投稿者／所有者の永続参照 | 独立して復元する |
| 画像ストレージ | アカウント画像とコンテンツ画像の実体・参照先 | アカウント画像をコンテンツ復元で削除・上書きしない |

以下はサービス固有の推奨であり、Googleがこのアプリのスキーマを規定しているものではない。

1. Identity Platform uidとは別に変更・再利用しないapp_user_idを用意する。対応付けの正はアカウントDBとし、コンテンツ側のusersは参照用の行・必要な表示情報へ縮小する。パスワード等を自前のアカウントDBへ複写しない。
2. 現users.idと新IDの移行対応を永続化する。復元で戻ったAUTOINCREMENT値から、新規登録者に既存人物の参照IDを割り当てない。表示名・メール・クライアント指定IDだけで既存利用者と認証アカウントを結び付けない。旧利用者への紐付け手順と確認証拠は別途設計する。
3. コンテンツ復元後は、現在のアカウントDBから参照行と最新のBAN・退会・公開状態を補い、Snapshot再評価と整合性検査を経て再開する。新規アカウントは投稿がない状態でも利用可能にし、古いコンテンツ側の情報から現在の認可を上書きしない。
4. アカウントDB復元でも、コンテンツやIdentity Platformに残るIDを別人へ再利用しない。復元後に欠けた対応は未解決として扱い、本人確認なしで再割当しない。削除／退会した人物への履歴参照を維持する最小レコード・匿名化の規則を決める。
5. Current Owner、Claim作者、Owned／Formerly Ownedはコンテンツの評価結果である。認証成功やユーザーDB復元だけで所有権を付与しない。通常Ownerの他人Claim判定、自己判定禁止、Acquire承認前後、Transfer後の権限移動と、管理者の別経路を既存不変条件どおり検証する。
6. Automation等のシステム主体と、実際にログインするアカウントを区別する。コンテンツ側の全users行を無条件にIdentity Platformのユーザーへ変換しない。
7. DB間の同時更新には単一DBのトランザクションを前提にできない。アカウント登録後のコンテンツ参照行作成・プロフィール／BAN反映を冪等化し、失敗後の再同期と、正のアカウント状態を確認できない場合の認可を設計する。

### 実装前に決めること

- アカウントDBとコンテンツDBを同じCloud SQLインスタンス内の別DBにするか、別インスタンスにするか。同一インスタンスならDB別export/importの手順を用意し、インスタンス全体の復元をコンテンツだけの復元と誤認しない。
- フォロー・お気に入り・DM・通知・signature_individual_idなど、アカウントとコンテンツの両方に関連する項目の正と復元方針。
- ユーザー画像・投稿画像の保存先と保持単位。現media全体の置換をそのまま流用しない。
- 登録・退会・BAN・Admin変更・認証アカウントリンクの監査、認証側とアカウントDB側の不一致の復旧手順。
- コンテンツ復元後も新規登録者・最新BAN・プロフィールを維持するテスト、認証方法追加でも同一人物になるテスト、アカウントDB復元時のID衝突と未解決参照のテスト。

Backups画面では、ローカル分離モードのGuitar / ChronicleとUser Accountsを個別に保存・復元できる。Cloud SQLの運用手順は引き続き別途実装する。

## ローカル実装：アカウント分離とダミー認証

`ygc-web` は標準で `local_dummy` を選択する。CLIや直接uvicornで起動する場合は `YGC_IDENTITY_BACKEND=local_dummy` を明示する。従来の未検証IDを利用する `prototype` モードは互換用として残し、ライブラリでの未指定時はこちらを使う。分離済みデータでprototypeへ戻す起動は拒否するため、以後は分離モードを継続する。

```sh
YGC_IDENTITY_BACKEND=local_dummy app/.venv/bin/ygc-web --no-browser
```

- `accounts.sqlite` はプロフィール・公開設定・User Type・BAN・固定 `app_user_id`・認証対応・権限の正を保持する。Follow・DMもこのDBが正。Automationを含む数値IDの予約は保持するが、システム主体はログインできない。
- Chronicleの `users`・Follow・DMは既存のJOIN／業務処理を維持するための投影。アカウント変更と投影はSQLiteのATTACH＋TEMP triggerで同一トランザクションに保存する。新しい接続で現在のアカウント状態を反映する。SQLite DELETE journalを必要とし、WALの既存DBでは自動切替せず停止する。
- 初回は `before_account_split_*.sqlite` を保存し、既存 `users.id` を維持してUUIDを割り当てる。既存のアバターを `account_media/users` へ複写する。数値IDとUUIDは変更・再利用できない。
- Browser Consoleから指定ユーザー／GuestでTop Pageを開く操作は維持する。ダミーはloopbackでのみユーザー選択を認証成功として扱い、サーバー発行のランダムトークンをタブごとに保持する。サーバーにはハッシュと1時間の期限を保存する。ID偽装・失効セッション・BAN・無効アカウントを拒否する。ログイン／テスト登録は別Originから利用できない。
- 利用者指定のquery・JSON・multipartの操作ID、本人設定・通知・お気に入りのパスIDをセッションと照合する。管理・Crawl・DB操作は従来のローカルConsole専用資格で別経路にする。ChatGPT MCPは独立した接続トークンで認証する。
- `LocalDummyIdentity` は共通 `ActorContext` へアカウントを解決する。これはローカル試験用であり、Identity PlatformのJWT検証器ではない。`K_SERVICE`／`CLOUD_RUN_JOB`では起動前に拒否する。GCP移行時はトークン検証器と認証対応付けを実装する。
- `role` は将来の管理権限用に保存するだけであり、Admin User TypeやAdmin Onlyモードは追加していない。現在の管理画面はConsole専用資格を使う。

### 仮サインインと将来の認証差し替え

GuestのSign Inはメールアドレス・パスワードのモーダルを開く。形式／空欄／重複チェックは行わない。画面は共通 `YGCAuth.signIn({email,password})` を呼び、現在のlocal_dummyアダプターは入力値を破棄する。フォーム末尾のTest userで既存ユーザーを選択する。HTTPに含めるのは選択したテストユーザーIDだけ。入力値をsessionStorage・DB・ログへ保存しない。キャンセル／成功時にフォームを消去する。

プルダウンは最後にログアウトしたユーザーを初期選択し、該当しなければ先頭を選ぶ。既存ユーザーがいない場合は登録を案内する。選択したユーザーでログインし、メール文字列からユーザーを推測しない。選択後に無効化／BANされた場合は拒否し、別ユーザーへ自動切替しない。user_id未指定の旧API呼び出しだけは互換用の専用Local Sign In Userを利用できる。これは明示的なローカル試験用の動作である。

`SignInResult` の応答はIdentity Platform RESTに合わせて `localId`、`idToken`、`expiresIn`（文字列）、`displayName`、`registered` を持つ。サービス側の `user_id`／`app_user_id` を追加する。ローカルidTokenはサーバー発行のランダムセッションであり、Google署名JWTではない。refreshTokenはnull、capabilities.refreshはfalseとし、未実装の更新機能を装わない。[Identity Platform RESTの認証応答](https://docs.cloud.google.com/identity-platform/docs/use-rest-api)

本番化ではブラウザのproviderアダプターをIdentity Platform SDK／RESTへ差し替え、取得した実ID tokenをサーバーで検証する。サーバーの `IdentityPlatformReplacement` とアカウント対応付けも実装し、検証済みissuer／tenant／uidからサービスIDを解決する。正規化した認証結果を画面に渡す契約を維持する。この契約を基に独立したクラウド認証画面を実装・配置済み。現行TopPage等のprovider置換は残る。

### 保存・復元の単位

Browser ConsoleのGuitar DB Management → Backupsで対象を選ぶ。各対象の手動保存・定期保存・保持世代・ダウンロード・復元を独立して操作する。閲覧／保存は通常モードでも可能、復元はメンテナンス中のみ。復元前に対象の現状を安全用バックアップとして保存する。

| 対象 | 保存するもの | 復元の動作 |
| --- | --- | --- |
| Guitar / Chronicle | ギター・Claim・Evidence・申請・係争・コンテンツ画像。互換用users投影も含む | アカウントの正・アバター・Follow・DMを巻き戻さず、最新プロフィール／BANを反映して必要なSnapshotを再評価する |
| User Accounts | アカウント・固定ID・認証対応・Follow・DM・アバター | コンテンツを置換しない。ローカルセッションは保存せず、復元時にも全破棄する |
| Operations | 運用設定・履歴 | 既存の運用バックアップ仕様を維持 |
| Authentication experiment | GPT実験のキュー・画像 | ユーザー認証DBとは別物。既存の実験バックアップ仕様を維持 |

Crawl前の自動バックアップはGuitar / Chronicleだけ。お気に入り・通知・signature guitar・Owned／Formerly Ownedはコンテンツ側に残す。ユーザーDB復元でバックアップ後のアカウントが欠ける場合はIDを予約した無効レコードを保持し、別人への再割当を防ぐ。アカウント無効化はログインを止めるもので、過去のClaimのBAN判定を自動変更しない。

別人のUUIDが同じ数値IDに存在するコンテンツ、未解決アカウント参照、認証subjectの再割当を伴うユーザーDB復元は拒否する。分離前の古いバックアップの復元には明示的なユーザー対応の移行が必要であり、表示名から推測して復元しない。GCP用の匿名化・退会・アカウントリンクの操作と監査、PostgreSQLでのDB間同期・独立復元は今後の実装対象。

## 登録プロフィールと同意

local_dummyの`POST /api/local-auth/register`は表示名、Account Type、Terms／Privacyへの同意と版のみ受け付ける。email/passwordなど未許可フィールドを拒否し、認証情報を送らない。アカウント作成・コンテンツへのユーザー投影・`accounts.account_consents`への版とサーバー時刻の記録は同一トランザクション。User Accountsバックアップに同意を含め、Chronicle復元から分離する。旧バックアップに同意がない場合は空テーブルを作り、既存ユーザーの同意を推定しない。

公開前に暫定Terms／Privacyを正式文面・版に差し替える。Identity Platform移行時はメール／パスワードを認証SDKへ渡し、検証済みUIDにアカウントと同意を関連づける。メール確認済みトークンをサーバーで検証してClaim／所有権申請を許可する作業は未実装。local_dummyではメール確認を実施した扱いにしない。

管理者権限、モードごとの許可範囲、メンテナンス中のReset・復元、ローカル現状維持方針は[管理者権限とメンテナンス制御](ADMIN_AND_MAINTENANCE.md)にまとめる。クラウドのAdmin資格・4モード・状態確認とモード操作は実装済み。コンテンツ管理、復元／リセット、ジョブ排他への接続は残る。
