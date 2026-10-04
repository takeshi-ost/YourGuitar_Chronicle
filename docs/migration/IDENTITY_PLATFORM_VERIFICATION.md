# Identity Platformのサーバー検証

2026-10-04、`ygc.identity_platform.IdentityPlatformIdentity` を追加。WebUIへの接続前に認証境界単体を実装・隔離検証する段階。ローカルのダミー認証は継続する。Cloud Runへの配置や実アカウントでの接続確認はまだ行っていない。

## 検証とID対応

公式Firebase Admin Python SDKでID tokenを検証する。プロジェクトIDを明示し、`check_revoked=True` を毎回指定する。署名・期限・発行元・対象プロジェクトの確認に加え、Google側の失効・無効化を確認する。Auth Emulatorの設定が存在する場合は起動・認証を拒否する。

検証結果の `(issuer, tenant, subject)` からPostgreSQL Accountsの既存identity_linksを参照し、ActorContextにアプリUUIDと参加者IDを返す。毎回正本を読むため、停止・BANは古いChronicle投影で解除できない。メールアドレスや表示名による自動紐付け・認証時の自動登録は行わない。クライアントが別ユーザーIDを指定した場合は拒否する。Admin資格はJWTの任意の値で決めず、既存のAccounts正本と業務処理で判定する。

テナントを使用する場合は明示設定し、SDKのテナント専用クライアントと結果の両方で照合する。JWTの検証済み状態とメール確認済み状態は別であり、このアダプターだけではメール確認を必須にしない。

## 接続時の前提

- 固定依存は `python scripts/install_dependencies.py --postgres --identity` で導入する。CIの全依存導入には `--browser --postgres --identity` を使用する。
- 初期化には `IdentityPlatformIdentity(accounts, project_id=..., tenant='')` を使用し、終了時に `close()` を呼ぶ。従来の `IdentityPlatformReplacement` 名も明示引数を要求する接続口として残す。
- 実行資格はApplication Default Credentialsを利用する。サービスアカウント鍵やWeb用apiKeyをサーバー検証の秘密鍵として使用しない。
- 失効・無効化確認にはユーザー照会権限 `firebaseauth.users.get` が必要。2026-10-04、実行用サービスアカウントにこの1権限だけの独自ロールを付与し、IAMで確認済み。実行用資格での実token確認はまだ行っていない。[Cloud SQL接続・権限確認](CLOUD_SQL_INITIALIZATION.md)を参照。
- Googleへの接続・資格・権限の失敗は認証拒否となる。失敗時にダミー認証へ切り替えない。公開エラーにSDK例外内のトークン等を転載しない。

## 残る実装

Google認証後のアプリ登録APIとステージング同意草案は後続の実装ブランチに追加した。[クラウド登録API](CLOUD_ACCOUNT_REGISTRATION.md)を参照。ブラウザSDK・メール確認・正式なTerms/Privacy、全Webルートの認可、PostgreSQLへの残る業務処理移植を続ける。ローカルの「メール・パスワードは送信も保存もしない」という仮登録説明を実登録へ流用しない。

現行WebUIのCloud Run起動拒否は維持する。認証検証の追加だけでは、SQLite・ローカル画像・プロセス内ジョブがクラウド対応になったことにはならない。

## 隔離検証

外部の証明書取得・Googleユーザー照会・Accountsの読取りを置き換え、公式SDKの署名・期限・失効検証は実際に実行する。テスト内の一時RSA鍵で署名したtokenを使い、正常・期限切れ・署名不一致・失効・無効化を確認する。別プロジェクト・別テナント・未登録／停止アカウント・IDなりすまし・Emulator拒否も確認する。実GCP資格や実ユーザー情報は不要。

検証結果：認証境界26件、Python全471件、JavaScript55件、ブラウザ共通UI・27モーダル・ユーザー操作、使い捨てPostgreSQL 18の4DB統合確認が通過。Python最終確認ではloopbackの1件がサンドボックス権限で拒否されたため、その1件を通信許可付きで再実行して通過を確認した。依存整合・スキーマ生成物・actionlintも通過。今回ブランチのGitHub CIと実GCP接続の成功を表すものではない。

公式参照：[ID tokenの検証](https://firebase.google.com/docs/auth/admin/verify-id-tokens)、[セッションの管理](https://firebase.google.com/docs/auth/admin/manage-sessions)、[テナント管理](https://docs.cloud.google.com/identity-platform/docs/multi-tenancy-managing-tenants)、[アクセス制御](https://docs.cloud.google.com/identity-platform/docs/access-control)。
