# クラウドの所有登録・Acquire審議

2026-10-06。所有登録・Acquire申請を段階的に接続する。現在の実装は審議担当の認証とMCP接続診断までであり、クラウドのListing/Acquire申請・写真提出・審議結果反映・Owner承認は未接続。Ownedの実データ確認を完了扱いにしない。

## 認証境界

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

検証：Python830件・JavaScript71件・ブラウザ・隔離PostgreSQLが成功。署名検証の呼出しと正しいaudience、異なるissuer/sub/email/audience、匿名・通常ユーザー資格の拒否、診断の非更新、トークン発行先制限と401の非再送を確認。実Google認証とクライアント登録は配置後に確認する。
