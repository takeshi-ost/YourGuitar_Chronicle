# クラウドConsoleのギター閲覧

2026-10-05。Cloud Run版BrowserConsoleにChronicleのギター一覧・検索・ページ送り・Product Detailを追加する。ローカル版の全機能を移植した段階ではない。

## 操作

メール確認済みAdminでConsoleへ入ると、左のGuitar DB Managementに一覧を表示する。メーカー・モデル・シリアル番号を検索し、25件ずつ前後へ移動できる。Detailボタンは右のProduct Detailへ情報を表示し、右側をその位置へスクロールする。その後も左右は独立してスクロールできる。未選択時も詳細欄は画面に合わせた高さを持つ。空DBは「該当するギターはありません」と表示する。

メンテナンスを含む全サービスモードで、Adminにはこの読み取り入口を許可する。一般ユーザーとGuestの閲覧入口ではない。ギター情報の取得失敗で、Operationsによるモード変更を停止させない。資格が失われた場合やSignOutでは、取得済みの一覧・詳細を破棄する。

## APIとDB

- `GET /api/admin/guitars?q=...&after=...&limit=...`：既定25件、最大50件。ID昇順のkeysetページ。次の開始IDを返す。
- `GET /api/admin/guitars/{id}`：指定した個体の基本情報のみ。

JWTを公式SDKで確認し、Accounts正本の有効なAdminと確認済みメールを必須とする。DB読み取りの間も正本資格とOperationsのロックを保持する。利用者指定のユーザーID・未知のクエリ・重複パラメーターは拒否する。IDは正のBIGINTで、JSONでは十進文字列として返しJavaScriptの丸めを避ける。

取得項目はID、manufacturer、model、finish、year、serial_number、location_country、location_region、current_owner_name、current_owner_typeに固定する。現在所有者等は保存済みIndividual Snapshotの表示であり、この入口でObservationの再評価や所有権判定を行わない。Claim中心の所有権・判定権限の遷移規則は変更しない。

画像・内部保存参照・申請・非公開根拠・所有者の認証情報は返さない。Chronicle接続は読み取り専用トランザクションとし、検索はSQLパラメーター化する。`%`・`_`・バックスラッシュをエスケープして文字列として検索する。クエリは120文字まで、SQL実行5秒・ロック待ち2秒に制限する。ページを跨いだ全体Snapshotを固定する方式ではなく、同時追加・削除後の最新表示にはRefreshを使う。

画像配信・Chronicle表示・個体編集・Crawl・バックアップ／復元／リセットと、一般TopPageへの接続は後続作業。

## 検証

単体検証でJWT・メール確認・Admin資格・停止アカウント、不正／過大／重複クエリ、書込メソッドの拒否、障害時の内部情報非開示を確認する。使い捨て実PostgreSQLではkeysetページの重複防止、リテラルの検索、SQL注入拒否、固定項目、全サービスモードのAdmin閲覧と一般ユーザー拒否を確認する。ブラウザでは検索・空一覧・前後移動・右側詳細・HTML非実行・左右独立スクロールを確認する。隔離試験の個体データを実ステージングへ投入しない。

ローカルの統一検証はPython621件・JavaScript71件・共通ブラウザ・実PostgreSQLが成功した。依存定義・固定版とスキーマ生成の整合も確認済み。

## ステージング配置（2026-10-05）

Cloud Build `c42bef3b-90a6-44f2-8351-2dcc7ecd9d6e` が成功。イメージ `account-api@sha256:e3c583e311356e34b4cb052c36266c356c6201ebdb1e42af9a5caffd872c04e3` を `ygc-staging-accounts-00008-sg6` へ配置した。DBの初期化・更新・試験個体投入や既存ジョブの変更は行っていない。

実URLで画面・モジュール・readyの200と、一覧／詳細APIの未認証401を確認した。公式SDK初期化、匿名時のデータ欄非表示、デスクトップ／モバイル表示、配置前後のOffline維持を確認した。この試験では利用者の資格情報を送信していない。実Adminによる空DBの一覧表示は利用者確認事項。データ入りの実環境確認は、後続のCrawl接続後に行う。
