# Cloud Run認証確認画面

確認日：2026-10-04。これはIdentity PlatformとAccounts DBの接続を試すステージング画面。TopPage、BrowserConsole、Crawl、画像保存、所有判定APIのクラウド配置は含まない。

## 配置した構成

- URL：<https://ygc-staging-accounts-rgmjxrs5kq-an.a.run.app/account>
- プロジェクト：`your-guitar-chronicle-staging`、リージョン：`asia-northeast1`。
- Cloud Run：`ygc-staging-accounts`。1 vCPU / 512 MiB、リクエスト課金、最小0・最大1、同時処理8、タイムアウト30秒。
- 実行用サービスアカウント：`ygc-staging-app`。鍵ファイルなし。Cloud SQLのUnix socketを使い、DBパスワードはSecret Manager `ygc-staging-db-password` のversion 1を環境変数として受け取る。
- Web画面は公開。Accountsの参照・登録は、サーバーで検証したIdentity PlatformのBearerトークンが必要。Cloud Runの公開権限はYGCのAdmin権限ではない。
- Identity Platformの許可ドメインとWebキーのHTTPリファラー許可に上記ホストを追加。確認リンクの403修正後、WebキーのHTTPリファラーには当該プロジェクトのFirebase authDomainも追加済み。既存の許可とAPI対象制限を保持した。もう一つのCloud Run生成URLは認証試験用の許可に追加していない。
- データは初期化済みのCloud SQLを利用。起動時はスキーマ照合だけで、DDL・マイグレーション・SQLiteへの代替接続・Crawl・定期処理を実行しない。

Operations DBのサービスモードはofflineのまま。この独立した認証確認画面は、そのモードによる公開サービスの閲覧制御とは別の移行試験用画面。一般サービスを公開済みと扱わない。

## ビルドと再配置

`Dockerfile`は公式Python 3.12.14のイメージをdigestで固定し、既存constraintsとbuild-requirementsで依存関係を固定する。Linux amd64としてCloud Buildでビルドし、非rootユーザーで `python -m ygc.cloud_account_runtime` を起動する。

`.gcloudignore` と `.dockerignore` は許可リスト。アプリソース、依存定義、Dockerfile、ビルド設定だけを含み、ローカルDB、画像保存データ、`.venv`、Git履歴、資格情報、テスト成果物を送らない。初回実測は109ファイル／2.6 MiB。

専用ビルドアカウント `ygc-staging-build` の権限は、Artifact Registry `ygc-staging` へのwriter、専用バケット `your-guitar-chronicle-staging-build` のobjectViewer、プロジェクトのlogWriter。DB・Secret Managerへの権限を付与しない。ビルドログはCloud Loggingを利用する。

再配置は次の順序で行う。

1. 共通テストを実行する。アップロード対象を `gcloud meta list-files-for-upload` で確認する。
2. `cloudbuild.yaml` を使い、上記専用アカウント・東京リージョン・専用ソースバケットを指定して `gcloud builds submit`。`_IMAGE` にArtifact Registryのタグを指定する。
3. 成功したビルドの `results.images.digest` を取得する。
4. `scripts/deploy_cloud_account.py` に `--project`、`--region`、`--instance`、`--image`（digest必須）、`--api-key-resource` を指定する。WebキーはGCPから取得し、0600の一時設定ファイルは終了時に削除する。DBパスワードの値は取得しない。
5. スクリプトは非公開状態で配置し、許可ドメインを追加・API制限の保持を確認してから画面を公開する。公開URL、稼働・DB接続、無認証拒否、ブラウザ表示を確認する。

再配置の途中で失敗した場合はCloud Runの状態を確認する。スクリプトは失敗時に自動公開を続行しない。再配置中は既存サービスも一時的に非公開になるため、試験利用者がいない時間に実施する。

## 稼働確認

`GET /health` はプロセスの稼働、`GET /ready` はAccounts・Chronicle・OperationsのDB接続を確認する。正常時は `{"status":"ok"}`。DB接続失敗時のreadyは503と汎用メッセージで、資格情報や接続エラーの内容を返さない。起動時のスキーマ照合失敗はサービス起動を止める。

Cloud Runのstartup probeは `/health`。DB障害時に無意味な再起動を繰り返さないよう、DB接続をlivenessの条件にはしない。初回の実URL確認で `/healthz` がGoogle側の404になったため、外部監視にも使える `/health` を採用した。

初回構成確定時の配置：リビジョン `ygc-staging-accounts-00002-trh`。ビルド `3ffbab7c-ef73-4ff1-a789-64b281cd7b82`、イメージdigest `sha256:cfab45e0d15d15f804991bf6811bac348fc05f0866dbc9e6bceddad8e62b4fb4`。

## 検証範囲と残作業

ローカルの共通検証でPython522件、JavaScript65件、共通UI・27モーダル・ユーザー操作・クラウド認証画面、実PostgreSQLの4DB・登録・投影・権限検証が通過。配置手順の追加テスト2件では、既存ドメイン保持、API制限の意図しない変更時の公開拒否、一時設定ファイルの削除を確認。稼働確認URL修正後の関連42件も通過。

実URLで画面・公開設定・DB接続・無認証と不正トークンの401・未配置APIの404を確認した。公式Web SDKの読み込みと実ブラウザのデスクトップ／モバイル表示も確認した。

2026-10-04、利用者が一般メールアドレスによるCreate Account・再読込み後のログイン維持・SignOut・Sign Inを確認した。これは利用者による実環境試験結果であり、エージェントによる代理登録ではない。失効・無効化の確認は残る。まだ実ユーザーをエージェントが作成したり、メールを送信したりしていない。規約・プライバシー本文はステージング草案。Accounts投影ワーカーは[専用Jobとして配置済み](ACCOUNT_PROJECTION_JOB.md)。公開前の正式版整備と、残りのWebUI/API・Storage・Crawl等のJobs移行は別途必要。

公式参照：[Cloud Runコンテナ要件](https://docs.cloud.google.com/run/docs/container-contract)、[Secret Managerの設定](https://docs.cloud.google.com/run/docs/configuring/services/secrets)、[専用ビルドアカウント](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)。

## メール確認追加後の配置

認証画面をリビジョン `ygc-staging-accounts-00003-ncs` へ更新した。確認メール送信と、新しいJWTによる確認状態更新を追加。操作・実配置・検証範囲は[メール確認](EMAIL_VERIFICATION.md)を参照。Accounts同期Jobの配置イメージ・スケジュールは変更していない。

## 管理API基盤追加後の配置

リビジョン `ygc-staging-accounts-00004-6sz` へ更新し、公開サービス状態と認証済みAdminのOperations APIを追加した。readyはOperationsを含む3DBの接続を確認する。BrowserConsole自体は未配置。[クラウド管理API](CLOUD_OPERATIONS_ACCESS.md)に実装範囲・初回Admin用の非公開Jobを記載した。
