# Identity Platformのメール確認

更新日：2026-10-04。一般WebUIの所有権申請をクラウド認証へ接続する前に、独立した[認証確認画面](CLOUD_RUN_ACCOUNT_STAGING.md)へメール確認の操作を追加・配置した。現行ローカルのダミー認証でメール確認した扱いにはしない。

## 操作

1. `/account` で登録済みアカウントにSign Inする。
2. 未確認の場合は「確認メールを送信」を押す。自動送信は行わない。
3. 受信メールのリンクを開き、Googleの確認画面でメールアドレスを確認する。
4. YGCへ戻り「確認状態を更新」を押す。「メールアドレスは確認済みです。」に変わることを確認する。

Googleからの確認メールはUIの選択言語をSDKのlanguageCodeに設定して送る。リンク確認後の戻り先は同じoriginの `/account`。送信先メールアドレスをYGC APIへPOSTすることはなく、公式SDKのログイン中ユーザーへ送信する。確認済みのサーバー判定を受けた場合は送信ボタンを隠し、再送しない。

登録・送信・確認状態更新・SignOutは同じ直列化キューで実行する。未ログイン、アプリ未登録、YGC側で利用を拒否されたアカウントは、この操作経路からメールを送れない。Googleの送信制限や通信エラーは既存の翻訳済みメッセージで表示し、送信失敗を確認済みに変えない。

## 確認済み状態の根拠

SDKのreloadでGoogleユーザーを更新し、getIdToken(true)で新しいID tokenを取得して `/api/auth/me` へ送る。サーバーは署名・期限・issuer／audience／tenantと失効・無効化を検証し、JWTのemail_verifiedが真のbooleanである場合だけ確認済みを返す。SDKのemailVerified、画面の状態、ブラウザから申告された値を権限の根拠にはしない。

メール確認はGoogleの属性であり、AccountsのProfile本文へ複写しない。確認状態更新は読取りAPIだけを呼び、アカウント・コンテンツを更新しない。通常の再読み込みではSDKが保持するトークンがまだ古い場合があるため、リンク確認後は「確認状態を更新」を使う。

この変更で所有権申請APIの移植・確認済み必須化を完了した扱いにはしない。今後のクラウドClaim／Acquire／Listing APIは、操作のたびに検証済みJWTの属性を確認し、未確認をサーバーで拒否する。表示ボタンの制御だけで保護した扱いにしない。

## GCP設定と検証

既存のIdentity Platform Email/Passwordを使用する。認証ドメイン、許可ドメイン、APIキーのリファラー制限は[配置手順](CLOUD_RUN_ACCOUNT_STAGING.md)と共通。既存キーのAPI対象にidentitytoolkit.googleapis.comとsecuretoken.googleapis.comが含まれることを確認した。テンプレートの独自変更や、Google側の確認済み属性を管理者権限で強制設定する処理は追加しない。

Python532件、JavaScript71件、共通ブラウザ・クラウド認証ブラウザ・実PostgreSQL回帰検証が通過。JavaScriptには確認済み再送防止・Google送信制限を含む関連16件を含む。JavaScriptでSDKだけのフラグをサーバーの判定へ置き換えないことを確認。ブラウザでは送信が明示クリック時だけであること、未確認→確認済み、再読み込み・SignOut・日英・モバイルを検証した。Googleの外部処理だけをfixtureで置換し、実メールは送信していない。

Cloud Runリビジョン `ygc-staging-accounts-00003-ncs` へ配置し、公式SDKの読み込みと未ログイン時の表示、health／readyの200、不正トークンの401を確認した。ビルド `107513f9-dec3-4a68-ad95-a29bd8c1e74d`、固定image digest `sha256:3ec4986d065a72727ec64c2ab8976d8f51af7e5ee3d7cdcea959c044f9125113`。実受信・リンクの消費・確認済みJWTは利用者による次の実環境試験。基本認証試験は既に完了しているが、メール確認・失効・無効化の試験とは区別する。

公式参照：[メール確認の送信とメール言語設定](https://firebase.google.com/docs/auth/web/manage-users)、[Userとトークン更新](https://firebase.google.com/docs/reference/js/auth.user.md)。

## 確認リンクの403修正

利用者の実リンク試験でFirebase標準ハンドラーのリファラーが拒否された。Cloud Runのoriginだけが許可され、`https://your-guitar-chronicle-staging.firebaseapp.com/*` が漏れていたため、既存制限を保持して追加した。配置スクリプトもWeb画面とauthDomainの両方を追加・照合するよう修正し、回帰テストで保持と追加を検証する。確認リンクの再試験は利用者が行う。
