# ブラウザのGoogle認証とステージング確認画面

更新日：2026-10-04。ブラウザ部品と登録APIはPR #18までmainへ統合済み。独立した[認証確認画面をCloud Runへ配置](CLOUD_RUN_ACCOUNT_STAGING.md)し、実ブラウザでSDKの初期化を確認した。実ユーザーでの登録・ログイン試験は次の段階。現行TopPage／Browser Consoleのローカル仮認証は維持する。

## 接続部品

`static/identity-platform-auth.js` は公式Firebase Web SDKにメール・パスワード認証を委ねる。SDKは `cloud-auth-loader.js` から公式CDNの固定版12.19.0のApp／Authモジュールを読み込む。AnalyticsやFirestoreは使用しない。読込みや認証が失敗してもダミーへ切り替えない。

認証の永続化は `browserSessionPersistence` とし、SDKの初期復元完了を待つ。アプリは独自のtoken／refresh token保存を追加しない。Google認証のセッション保存・更新はSDKが担い、APIへ送るID tokenはリクエストごとに `getIdToken()` から取得する。認証操作は順番に実行し、登録とSignOutの競合を避ける。

メール・パスワードはSDKに渡す。YGC登録APIのJSONにはプロフィール・同意だけを含める。認証付き通信は同じoriginの `/api/` に限定し、redirectを拒否する。現行local-auth.jsのfetch置換や仮ユーザー選択をクラウドの資格取得へ流用しない。

## 操作フロー

- Create Accountは、最新の文書版と同意・プロフィールを確認してからGoogleの認証アカウントを作り、アプリ登録APIを呼ぶ。
- Google登録後にアプリ登録だけが失敗した場合、Googleアカウントを削除しない。認証状態を保ち、同じ主体でアプリ登録のみを再試行する。
- Sign Inの後にmeがregistration_requiredを返した場合、認証済みのままプロフィール・同意の入力へ進む。ログインだけでアプリユーザーを作らない。
- Googleに登録済みでログアウトしている場合はSign Inしてからアプリ登録を完了する。別メールのアカウントを作る場合は先にSignOutする。
- 同意文書が更新された場合、Google登録を始めず、最新文書を取得してチェックを解除し、再同意を求める。
- SignOutはSDKのセッションと画面上のアプリIDを解除する。パスワード入力は成功・失敗とも処理後に空にする。SDKの生の例外文は画面へ転載しない。

## 確認画面の提供条件

`cloud_account_api.create_app(settings, project_id=..., tenant='', web_config=...)` にWeb構成を明示した場合だけ、`/account` と `/api/auth/config`、必要な静的素材を追加する。web_configの項目はapiKey・authDomainのみ。projectIdとtenantはサーバー検証器の設定から返す。現在のステージングではauthDomainは `<project_id>.firebaseapp.com` に一致させる。

apiKeyはGoogleが提示したWeb用の公開設定であり、DBパスワードやサービスアカウント鍵をここへ入れない。設定値はリポジトリへ直接埋め込まない。設定を省略すると従来どおり認証APIのみとなる。

確認画面には、実認証としてGoogleへ送信する旨と試験データのリセット可能性を表示する。日本語／英語の言語切替、5種類のAccount Type、文書のモーダル閲覧・外クリックによる閉じる操作に対応する。これを現行TopPageの代わりとして公開しない。

## 検証

JavaScriptでは、資格情報の分離・tokenの都度取得・登録失敗後の再送・未登録ログイン・文書更新・異なる主体の混同拒否・外部origin／redirect拒否・SignOutとの競合を確認する。

ChromiumではGoogleの外部SDK操作を試験専用モジュールへ置き換え、実際の確認画面とアプリAPIを接続する。登録失敗後の再試行、リロードでのセッション復元、Sign In／SignOut、未登録主体の登録、日本語、文書外クリック、スマートフォン幅を確認する。Googleへの実登録・メール送信は行わない。公式SDKの署名・失効検証と実PostgreSQL登録は別の既存統合テストで確認する。

今回の隔離検証：Python504件・JavaScript65件、既存ブラウザ操作・27モーダル、新しい認証確認画面の操作、PostgreSQL 18の4DB統合確認が通過。依存整合・スキーマ生成物・actionlint・配布wheel同梱も確認済み。最終の画面調整後は認証確認画面を再実行した。実GCPの成功や今回ブランチのGitHub CI通過を示すものではない。

## 残る作業

現行WebUIの残るSQLite業務処理の移植、TopPageへの認証部品組込み、メール確認の案内／制御、投影Workerのクラウド配置、Cloud SQL接続、実行サービスアカウントのユーザー照会権限、実Google認証・デプロイ後の統合確認。確認画面の実装はこれらの完了を意味しない。

関連：[アプリ登録API](CLOUD_ACCOUNT_REGISTRATION.md)、[サーバーtoken検証](IDENTITY_PLATFORM_VERIFICATION.md)。公式参照：[SDKのCDN導入](https://firebase.google.com/docs/web/alt-setup)、[認証状態の永続化](https://firebase.google.com/docs/auth/web/auth-state-persistence)、[メール・パスワード認証](https://firebase.google.com/docs/auth/web/password-auth)。

## メール確認

認証画面へ確認メール送信・確認状態更新を追加した。公式SDKの送信は利用者のクリック時だけ行い、状態更新は新しいJWTをサーバーで検証する。[操作・検証範囲](EMAIL_VERIFICATION.md)を参照。クラウド所有権申請APIの接続・確認済み必須化は後続の移行として残る。
