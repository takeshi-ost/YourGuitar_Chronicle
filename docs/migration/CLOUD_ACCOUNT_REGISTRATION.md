# Google認証後のアプリ登録・ログインAPI

更新日：2026-10-04。認証APIはmainへ統合済み。独立した[認証確認画面をCloud Runへ配置](CLOUD_RUN_ACCOUNT_STAGING.md)し、実Cloud SQLへの接続と不正トークン拒否を確認した。実ユーザーでの登録試験と現行WebUIへの組込みは残る。

## 認証とアプリ登録を分ける

メール・パスワードによるGoogleアカウントの作成／ログインはブラウザ側でIdentity Platformに対して行う。そのID tokenをAuthorizationのBearerとしてアプリAPIへ送る。アプリ側は公式SDKで検証した主体からAccounts正本のIDを解決する。メール・表示名で既存ユーザーと自動連結しない。

Google認証が成功しても、YGCの表示名・Account Type・規約同意が完了していなければアプリ未登録として扱う。アプリ登録APIはプロフィールと同意だけを受け取り、email・password・user_id・issuer・subject・tenant・role等の指定を拒否する。ID token自体にはメールアドレスが含まれる場合があるが、アプリのアカウント登録・投影には保存しない。

## API

| API | 認証 | 結果 |
| --- | --- | --- |
| GET `/api/auth/registration` | 不要 | 現在のTerms／Privacy、文書版、identity_platformモード |
| POST `/api/auth/register` | Google ID token必須 | 検証済み主体のアプリ登録。既存なら元のアカウントを返す |
| GET `/api/auth/me` | Google ID token必須 | Accounts正本の現在のアカウントとメール確認状態 |

registerの項目は `display_name`、`account_type`、`terms_accepted`、`privacy_accepted`、`terms_version`、`privacy_version`。表示名は空白除去後1～120文字。Account Typeはuser・shop・builder・repairer・organization。両同意はbooleanのtrue必須で、表示した文書の版と一致させる。ローカルとクラウドで同じ項目検証を使う。

アカウント・認証ID対応・同意日時／版・投影outboxはAccounts内で同一トランザクションに保存する。再送信や同時送信で別アカウントを作らず、既存プロフィールや初回同意を書き換えない。新規roleはmemberで、Admin資格をフォームから取得できない。

meは未登録なら409と `code=registration_required` を返す。自動登録しない。無効tokenは401、停止／BAN等の利用不可アカウントは403。障害時にダミー認証へ切り替えない。応答はno-storeとし、ユーザーID・UUID・表示名・Account Type・role・メール確認済みフラグに限定する。プロフィール全体や認証主体・SDK例外の内部情報は返さない。メール確認フラグは案内用であり、この段階では確認済みを利用条件にしていない。

## 組込みと起動

`ygc.cloud_account_routes.account_router(verifier, documents)` は完成後のクラウドWebアプリへ組み込める。verifierは `IdentityPlatformIdentity` を使い、同じverifierのAccounts正本へ登録する。

`ygc.cloud_account_api.create_app(settings, project_id=..., tenant='')` は認証APIのみのFastAPIアプリを作る。起動時にAccounts／Chronicleの002スキーマを確認し、終了・起動失敗時に公式SDKのアプリを解放する。SQLiteやローカルジョブは起動せず、未移植のAPI・WebUIは提供しない。依存には `--postgres --identity` が必要。

これはステージング統合用の部品であり、現行 `ygc-web` の代替ではない。現行WebUIはlocal_dummy／prototypeのまま。Cloud Runの現行起動拒否も維持する。

## 同意文書と登録失敗

`cloud_registration.py` にステージング試験用のTerms／Privacy草案を置く。Googleで実認証を行うこと、YGC側の保存項目、テスト中のリセットを明記する。local-draftの「メール・パスワードを送信しない」説明を実登録に流用しない。一般公開前に正式文書へ変更し、版も更新する。

Googleの認証登録とYGCのDBトランザクションを一括コミットできない。Googleアカウント作成後にアプリ登録が失敗した場合、その認証アカウントを勝手に削除しない。ログインを維持／再ログインして、アプリ登録APIだけを再試行する。ブラウザ側の案内・再試行フローは後続ブランチの[認証確認画面](CLOUD_BROWSER_AUTH.md)に実装した。現行TopPageへの組込みは未完了。

Chronicleへの投影は登録トランザクションとは別。Workerによる投影完了までコンテンツの変更は既存の同期境界で拒否される。認証成功を投影完了やOwner資格の付与と混同しない。

## 検証と残作業

隔離HTTPテストでtoken拒否・未知／停止アカウント・同意版不一致・秘密情報／権限指定拒否・起動失敗の後片付けを確認する。実PostgreSQLの使い捨てDBではHTTP経由の同時登録・再送信・同意の原子性・5種のAccount Type・120文字の表示名・投影結果を確認する。今回の検証はPython499件・JavaScript55件、共通UI・27モーダル・登録／ログイン／Listing／Acquireのブラウザ操作、PostgreSQL 18の4DB統合確認が通過。依存整合・スキーマ生成物・actionlintと配布wheelへのAPI部品同梱も確認した。実GCP接続や今回ブランチのGitHub CI成功を示すものではない。

Googleへの署名・失効検証は[認証検証](IDENTITY_PLATFORM_VERIFICATION.md)の公式SDKテストで別途確認する。

後続ブランチにGoogle SDKと確認画面を追加した。残る作業は、現行TopPageのフォーム／認証表示の切替、メール確認、全WebルートのPostgreSQL移植と認可、投影Workerの配置、実サービスアカウントのユーザー照会権限とCloud SQL接続確認。まだ実ユーザー登録は開始していない。

公式参照：[ブラウザのメール・パスワード認証](https://firebase.google.com/docs/auth/web/password-auth)、[サーバーでのID token検証](https://firebase.google.com/docs/auth/admin/verify-id-tokens)。

## 本人プロフィール編集（2026-10-05）

認証確認用Accountページに、メール確認済みの登録ユーザーのプロフィール表示・編集・再取得を追加。対象は表示名（必須・120文字まで）、国・地域（各120文字まで）、自己紹介（2000文字まで）。取消し・Escape・外クリックでは保存しない。保存後はAccountの表示名とプロフィールを再取得し、再読み込み・再ログインでも正本の内容を表示する。権限・BAN・アカウント種別・認証資格情報は編集できない。

`GET / PUT /api/auth/profile` はGoogleの検証済み主体からAccounts正本のUUIDを解決する。操作対象は正本の本人レコードのみで、URLクエリや本文による他ユーザー指定を拒否する。未確認メール・無効アカウントを拒否し、読取りは編集項目と比較版だけを返す。応答はprivate, no-store。

本人操作はサービスモードに従う。Normalでは閲覧・編集可能、Read onlyでは閲覧だけ、Offlineでは両方を拒否する。Admin Onlyでは正本Adminの本人に限定する。Accountページの本人編集はAdminでもRead only / Offlineを迂回しない。メンテナンス中の管理者修正はBrowser Consoleの明示的な管理者プロフィール編集を使用する。

保存は管理者プロフィール編集と処理を共有し、正本アカウントとモードのロックをコミットまで保持する。比較版の不一致を409で拒否し、Crawl・復元・初期化と共通排他を取る。プロフィール・同期outbox・操作主体/対象UUIDと変更項目名/版/時刻の監査を同一Accountsトランザクションに保存する。監査にはプロフィール本文を複写しない。関連個体への反映は既存の定期投影Jobで行う。OwnerのID・所有分類・Claim判定権限は変えない。保存結果が不明なときは自動再送せず、再取得してから操作する。

配置後のブラウザ確認：

1. Normalでメール確認済みの一般ユーザーとしてAccountページを開き、元の4項目を記録する。
2. 編集モーダルの取消し・Escape・外クリックで変更されないことを確認する。
3. 4項目を保存し、表示名・プロフィールが再読み込みとSignOut→Sign In後も保持されることを確認する。
4. 2タブで同じユーザーを開き、一方の保存後に古い表示からの保存が拒否され、再取得後に編集できることを確認する。
5. Read onlyでは閲覧できるが保存は拒否され、Offlineではプロフィール操作が制限されることを確認する。モード変更はAdminのBrowser Consoleで行う。
6. SignOut後にプロフィールが消えることを確認し、項目とモードを元へ戻す。所有履歴がある場合のみ、同期後のOwner名更新と分類維持を比較する。

一般公開用TopPage/User Profileへの組込み、所有一覧の一般ユーザーAPI、権限変更・BAN操作は後続範囲。今回の接続にDBスキーマ・IAM・投影Jobの変更は不要。

隔離検証：Python790件・JavaScript71件・共通ブラウザ・実PostgreSQLが成功。本人限定と他ユーザー不変、未確認メール/無効主体の拒否、全モードの閲覧/編集制限、比較版競合、監査失敗時のロールバック、メンテナンス排他を確認。ブラウザで取消し・Escape・外クリック、保存/再表示/競合/SignOutとモバイル表示を確認。本人Ownerの変更を投影後に再評価し、Owner名更新とID/Owned分類維持を確認した。自己判定禁止・Acquire承認前後・A→B→C・管理者別経路の共通回帰も成功。実クラウドの利用者受入は配置後に記録する。
