# 正式UIのクラウド統合：主要3画面の限定プレビュー

基準：main `aaf07c94161afd8a086f30b081d84e529c95e2dc`。実装ブランチ `feat/cloud-formal-ui-shell`。
既存ローカル画面のデザインを維持し、既存クラウドAPIへ接続した主要画面の限定プレビュー。正式UI全体の完成を意味しない。

## 利用できる画面

- `/ui`、`/ui/guitars/{id}`：既存正式ロゴ、Sunburst、二段ヘッダー、一覧／詳細、サインイン／サインアウト、検索、履歴、戻る／進む。狭幅では詳細パネルを使用する。
- `/ui/profile`：本人情報編集、本人画像の操作UI、公開設定、Owned／Formerly Owned／私的Favorite、申請、Claim、通知と対象詳細への導線。
- `/ui/members`：会員検索、Follow／Unfollow、既存の認可付き会員アイコン。
- `/`、`/account`、`/members`、`/console` の既存画面も維持する。新規登録・メール確認など既存認証画面への導線を保持する。

## データと公開境界

既存の `user-view.css`、`themes.css`、ロゴ、木目、共通UI部品を再利用。ローカル認証、`viewer_id`、SQLiteへは接続しない。既存APIと認可・サービスモードを使用し、新たな公開DTOや認可モデルを追加しない。本人切替・サインアウト・失権時は表示を破棄する。

会員アイコンのPublic／Members／Followers／Private制約とGuest拒否を維持する。非公開Evidenceを公開ギター写真に代用しない。認証・DBスキーマ・IAM・既存Jobsの変更は含まない。

## 未完了・未移行

- **画像アップロードの実操作QAは利用者の拒否により未確認。** 自動テスト成功と実操作確認を混同しない。拒否されたアップロードを再試行・別経路で実行しない。
- 横断UserChronicle、New Discovery、統計、地図、テーマ設定のクラウド保存は未移行。
- 他人の詳細プロフィール、他人のOwned／Formerly Owned一覧、ギター写真の公開は未移行。公開範囲・配信／撤回モデルの判断を要する。
- DMなど追加APIが必要な機能は未接続。今回のリリースで追加機能や新たなブラウザQAは行わない。

## 検証記録（2026-10-08）

- 最終Python：**2,422件成功**（既存警告3件）。`/tmp/ygc-formal-release-python-final.log`、対応resultはexit 0、source_changesなし。
- JavaScript：**909件成功**。既存全ブラウザ回帰、隔離PostgreSQL 18.6の全対象検証も成功。ログは `/tmp/ygc-formal-release-regression.log`。
- 回帰runner全体の初回exitは1。原因はPythonの一時ストレージ分離テスト1件の失敗であり、同一ソースの最終Python再実行で上記2,422件成功を確認した。回帰ログ単体を全体exit 0とは記載しない。
- 終了時の既存Playwright `Target closed` 非同期警告を記録。ブラウザ各検証は成功している。
- 3画面×3幅（1440／390／320px）×3テーマの27条件、正式ロゴ重複と狭幅修正後の実Chrome PC／390／320pxは引継ぎ済み検証。本リリース工程でブラウザは操作しない。
- 保存された回帰入力manifest `/tmp/ygc-formal-release-regression-inputs.json` の**387ファイルを現在ファイルとSHA-256照合し、不一致0**。文書更新前に差分と未追跡ファイルを別のリリース証拠ディレクトリへ保護した。
- 既存の独立レビューでは重大認可漏れは未検出。実データへの書込み試験は行わない。

## ステージングリリース

利用者の2026-10-08承認に基づき、commit／push／draft PR、正確なHEADのCI、main統合とmain CI、Cloud Build、既存Webへのimage更新を行う。秘密・ローカル画像・DB・テスト成果物をビルド送信対象に含めない。

配置後のHTTP／API／read-only DB確認が成功してから、現在値を再確認し、サービスモードをOffline v13からAdmin OnlyへCASで切り替える。Review OFF／Crawl OFFを維持。全有効・メール確認済みAdminは既存業務権限の範囲で閲覧・更新可能、一般ユーザー／GuestのAPIは拒否する。認証トークンの抽出・新規発行・ログインは行わない。資格情報やブラウザ承認が必要なら停止する。

確認URL：<https://ygc-staging-accounts-rgmjxrs5kq-an.a.run.app/ui>。利用者の確認完了連絡まではAdmin Onlyを維持する。commit／PR／CI／revision／digest／traffic／modeの実結果はリリース報告に記録し、未実施の工程を成功扱いしない。
