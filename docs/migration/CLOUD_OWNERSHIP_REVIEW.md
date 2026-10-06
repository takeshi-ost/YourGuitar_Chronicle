# クラウドの所有登録・Acquire審議

2026-10-06。所有登録・Acquire申請を段階的に接続する。審議担当の認証・MCP接続診断に続き、Listing/Acquire申請の作成・写真提出・本人確認・取消を実装。審議キューのMCP接続・結果反映・Owner承認は未接続で、提出後はpendingのまま。Ownedの実データ確認を完了扱いにしない。

## 認証境界

### 中断・次回の再開地点（2026-10-06）

利用者の依頼で作業を中断。直近のListing/Acquire申請受付・写真提出・本人表示・取消のクラウド実装は配置済みだが、下記「利用者確認」の6項目はまだ実施されていない。審議キュー・結果反映・Owner承認も未接続のまま。

次回はWeb版Codex Cloudの環境作成・審査専用認証・接続診断から再開する。Cloud接続確認後に、未実施の直近実装のブラウザ確認を再開する。環境作成の案内地点は「設定 → Codex Cloud → Environments → Create environment」。Web版への接続済み・実装受入済みと推定しない。

中断時の配置はPR #49（mainへマージ済み）、Cloud Run revision `ygc-staging-accounts-00028-l9b`。Web版へ移す方針と本中断メモは、チャット移行に伴う文書PRへ含める。[次回の引き継ぎ記録](../history/HANDOFF_2026-10-06.md)から再開する。中断中は追加の実装・配置・審議・サービスモード変更を行わない。

### 審議実行環境の変更方針（2026-10-06）

利用者の指定により、今後の審議担当はローカルPCのCodexではなくWeb版のCodex Cloudへ移す。以下に記載するローカルstdio設定は既存の接続診断用であり、最終的な運用方式ではない。現時点ではCloud環境の作成・認証・接続試験は未完了で、審議キューも未接続。

[Codex Cloud環境の公式手順](https://learn.chatgpt.com/docs/environments/cloud-environments)に従い、専用環境を作成し、リポジトリ・依存関係・通信先を設定する。ローカルの絶対パス、config.toml、gcloudログインに依存させない。専用SAの短期認証をCloud環境から取得する方式を別途設計し、既存のGoogle OIDC検証を維持する。ローカルの資格情報やSA秘密鍵をリポジトリへコピーしない。

環境公開後、新規Cloudタスクから接続診断を確認し、その後に画像取得・独立観察・結果提出を接続する。Cloudタスクでの実行と、申請を契機とする常時自動実行は別の受入項目とする。自動起動方式と利用可能な機能を確認するまで、PC不要の常時自動審議が完成したとは扱わない。採否・Owner承認・Review OFF時の保留は引き続きYGC側が管理する。

申請者はIdentity PlatformとAccounts正本で識別する。審議担当は専用SA `ygc-staging-review@your-guitar-chronicle-staging.iam.gserviceaccount.com`（不変ID `116488081755920377234`）のGoogle署名付き短期OIDCトークンで識別する。Cloud Runの正規URLをaudienceとして固定し、署名・有効期限・issuer・audience・subject・email・email_verifiedを確認する。通常のYGCログイントークンやAdminのメールだけでは審議担当になれない。

運営Googleアカウントに、当該SA上の `roles/iam.serviceAccountOpenIdTokenCreator` だけを付与する。SAにDB、Storage、YGC Admin、プロジェクト上の追加権限や秘密鍵は付与しない。IAM Credentials APIでIDトークンを発行し、最大50分メモリに保持する。固定キーやSecret値をクライアント設定へ記載しない。資格情報・内部例外はstdio/MCP出力に含めない。署名検証用の取得は10秒、接続は30秒でタイムアウトする。

[Googleの短期IDトークン](https://docs.cloud.google.com/docs/authentication/get-id-token)と[公式検証ライブラリ](https://googleapis.dev/python/google-auth/latest/reference/google.oauth2.id_token.html)を使用する。

## 現在の接続口

`POST /api/review/mcp` は有効な審議担当OIDCを要求する。initialize / ping / tools/listと `ygc_review_connection_check` のみ提供する。診断は `authentication=google_oidc`、`queues_connected=false`、`data_changed=false` を返し、画像取得や申請確保・DB更新を行わない。匿名やユーザーの認証を審議資格に代替しない。本文は100 KB以下、JSON RPC単体のみでバッチ・任意のツール名・任意引数は受け付けない。

配置スクリプトに `--enable-review-gateway` を追加。今後の再配置でもこのフラグを使用し、許可するSAの不変IDと既存サービスの正規URLを取得する。環境変数は `YGC_REVIEW_AUDIENCE`、`YGC_REVIEW_EMAIL`、`YGC_REVIEW_SUBJECT`。有効化しない構成に未認証の代替入口は作らない。

ローカルstdioブリッジ:

```sh
app/.venv/bin/python -m ygc.cloud_review_bridge \
  --url https://ygc-staging-accounts-rgmjxrs5kq-an.a.run.app \
  --service-account ygc-staging-review@your-guitar-chronicle-staging.iam.gserviceaccount.com \
  --gcloud /opt/homebrew/bin/gcloud
```

ブリッジは現在のgcloudログインから当該SAのIDトークンだけを発行する。HTTPリダイレクトや任意のホストへの送信を許可せず、401でも書込要求を自動再送しない。従来のlocalhost用 `ygc_experiment` は別設定として保持する。

[Codex公式MCP設定](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)のSTDIO設定に上記の絶対パスのPythonと引数を登録する。名前は `ygc_staging_review`、startup timeoutは60秒を使用する。現在の接続確認が済んだ後、申請キューのツール追加時にクライアントへ新しい定義を読み込ませる。

## 続く実装と受入

1. Listing/Acquireのプレビュー・Challenge・24時間期限・写真提出を本人認証とPostgreSQLへ接続する。非公開根拠写真はcontent Storageに固定generation参照で保存する。
2. MCPの確保・画像・独立観察の記録・登録仕様開示・結果提出・失敗報告を接続する。採否はYGCの既存ルールが決め、期待Serial/Challengeを観察前に返さない。
3. Review OFF中も回答を保持し申請/Claimへ反映しない。古いlease・取消・期限・初期化/復元・Crawl・重複登録・正本投影を反映時に再確認する。
4. Listingは通過後に個体/Positive Listingを作り、Acquireは現OwnerがユーザーならUnverifiedとして承認待ちにする。申請採用で現Owner承認を代替しない。
5. Current Ownerの他人Claim判定・自己判定禁止・A→B→Cの権限移動・Adminの別経路を、設計の遷移表と実PostgreSQLで回帰確認する。一般画面と管理画面から受入し、Owned/Formerly Ownedの未確認を解消する。

## 本人による申請・写真提出（2026-10-06）

`/account` に「所有申請」を追加。未登録ギターはMaker・既知Serial・仕様・取得日・説明を入力し、登録済み個体はGuitar IDを指定して申請する。Create applicationの明示操作で下書きをChronicleへ保存し、8文字のChallengeと24時間の写真提出期限を返す。未保存のChallengeプレビューは後続の一般TopPage統合時に接続する。下書き保存ではIndividual・Claimを作らず、所有状態を変更しない。

APIは `/api/auth/applications`、`/{revision}/photos/{closeup|overview}`、`/{revision}/submit`、`/{revision}/cancel`。Identity Platformの確認済み本人とAccounts正本の有効性を毎回確認し、対象申請はapplicant_idで限定する。Adminにも他ユーザーの申請・根拠写真をこの本人用APIから閲覧させない。管理者用の審査画面は別の後続範囲。

近接・全体写真は8 MiB／800万画素以下の静止JPEG・PNG・WebPを受け付け、最大辺2048pxのJPEGへ正規化して非公開content Storageに保存する。DBのimagesはbase64ではなく固定generation参照で、image_meta.storage=`gcs-content-v1`によりローカル方式と区別する。参照や署名付きURLを画面のJSONへ返さず、本人認証付きバイナリ配信だけを使用する。一般ギャラリーへ追加しない。モーダル外クリック・Escape・SignOutで画像URLとファイル入力を解放する。

同じ申請の作成・提出の再送を重複させない。Maker＋Serialの既存個体、Current Ownerの自己Acquire、既知Serialなし、係争、期限切れ、写真不足、未来日付、対象Serial変更を拒否する。日付はX-YGC-Timezoneで入力者の暦日を評価する。Acquire提出時に登録仕様と比較元をサーバーで固定し、既存Storage画像または承認済みReverb画像を取得できない場合は「比較元なし」に置き換えず停止する。期待値を審議担当へ開示する処理はまだ追加しない。

通常ユーザー操作のモード制限を適用し、Read onlyでは閲覧だけ、Offlineでは閲覧・提出とも停止する。Adminが本人申請を行う場合も通常の申請経路を使用する。Crawl／初期化／復元の共通mutexとAccounts投影確認を通して更新し、写真参照とイベントは同じChronicleトランザクションで保存する。未コミットの画像だけを補償削除し、保存済み画像はバックアップからの復元のため保持する。画像の物理整理は別の残作業。

一覧は進行中の申請を優先して最大50件、進行中は本人ごと最大25件。古い履歴のページ移動、一般TopPageからの個体選択、管理者表示、審議処理は後続。

Chronicle保存に申請と写真参照を含め、復元・初期化後の復元では通常Media画像に加えて根拠写真のgenerationを検証する。写真欠損時はDBの置換前に拒否する。この確認にはmaintenance Jobも同じ新しいイメージへ配置する必要がある。

利用者確認（未確認）:

1. Normalで `/account` に確認済み本人として入り、「未登録のギターを登録する」で下書きを作成する。Challengeと期限を確認し、個体総数・Ownedが増えないことを確認する。
2. 紙のChallengeとSerialを写した近接・全体写真を提出し、「審査待ち」、写真表示、再読み込み後の維持を確認する。外クリック・Escapeで閉じる。
3. BrowserConsoleで既存個体のIDを確認し、「登録済みギターの所有を申請する」で下書き・取得日・写真を提出する。現在Ownerの自己Acquireは拒否し、他ユーザー／外部Ownerの個体は提出だけでOwnerを変えない。
4. 下書き／審査待ちを取り消し、再読み込み後に取消済みであることを確認する。SignOut後や別ユーザーでは元の申請・画像を表示しない。
5. Read onlyでは申請閲覧・写真表示だけ、Offlineではこれらも停止することを確認し、試験後のモードを元へ戻す。
6. 根拠写真を提出した状態でChronicleを保存し、申請取消後に復元して申請・写真が戻ることを確認する。初期化→同じ保存から復元でも写真を確認する。ユーザー・Admin・ログインは維持する。

ここまででは審査による採用や所有権の移動は実施しない。Owner決定とOwned分類の内容確認は審議・承認を接続してから行う。

隔離検証：Python840件・JavaScript71件・Chromium・一時PostgreSQLが成功。申請の反復作成/提出、イベント保存失敗時のDBロールバックと画像補償削除、他人の写真拒否、申請期限、正本投影、Crawl/メンテナンス排他、写真欠損時の復元拒否を確認。既存のOwner移転・自己判定禁止・別経路のAdmin判定の回帰も成功。実サービスの操作受入は上記の利用者確認後に記録する。

検証：Python830件・JavaScript71件・ブラウザ・隔離PostgreSQLが成功。署名検証の呼出しと正しいaudience、異なるissuer/sub/email/audience、匿名・通常ユーザー資格の拒否、診断の非更新、トークン発行先制限と401の非再送を確認。

2026-10-06、PR #47をCI成功後にマージ・配置。実Google認証によるinitialize・tools/list・接続診断が成功し、匿名アクセスは401。health・ready・BrowserConsoleは200。Codexの既存設定を保持して `ygc_staging_review` を追加済み。現在のチャットのツール一覧への反映にはVS CodeのCodex拡張機能の再読み込みが必要。その後にチャットから診断ツールを実行し、上記の申請キュー実装へ進む。診断結果は `queues_connected=false`、`data_changed=false` であり、所有登録・Acquireの受入完了を意味しない。
