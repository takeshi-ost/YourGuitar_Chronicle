# 仮想PCへの開発引き継ぎ — 2026-10-06

## 保存状態

対象: takeshi-ost/YourGuitar_Chronicle。
ベースcommit: `6e2d90138cfadb42e638272ca7c990021465242d`。
作業用branch: `codex/cloud-review-ui`。変更は未コミット。push、PR作成、merge、配置なし。
Macの作業用チェックアウト: `/Users/t_oshita/Documents/Codex/2026-10-06/task-2/ygc`。
既存の `/Users/t_oshita/Documents/GitHub/YourGuitar_Chronicle` は同じベースcommitでcleanのまま。

この引き継ぎと全変更ソース、適用可能なpatchをソース移行アーカイブへ含める。アーカイブのMANIFEST.jsonが全ファイルと各SHA256、ベース・ブランチを記録する。アーカイブ自体のSHA256は同名.sha256に保存する。アーカイブは依存環境を含むフルリポジトリではない。仮想PCではGitHubからベースを用意してpatchを適用する。

## 実装済み

- Cloud審査MCP: Acquire/Listing各5ツール＋診断。private Storage固定generation、独立観察→登録仕様開示、原子的採否/Claim/通知反映。採否はYGCの既存共通ルール。
- Review OFF回答保留と再開時反映、期限・lease・取消・係争・参照更新・正本投影・BAN・競合Listingの検証、復元lease破棄。保留回答の復元時破棄。
- Current Ownerによる他人Claim判定API。自己判定禁止・譲渡後権限移動、Adminとは別経路。
- `/account`: OwnedからOwner判定内容確認→確定、判定後の所有一覧再取得、本人申請のClaim状態/採否理由、errorの確認付き再開。
- `/console`: Review ON/OFFの注意と確認、表示時の状態との比較更新。自動起動はしない。
- Listing証拠写真は非公開のまま保持。一般代表写真は公開同意・配信経路が整うまで追加しない。

## 移行前の検証（履歴）

最新版でPython **848 passed**、JavaScript **75 passed**、PostgreSQL18の4DB統合チェック成功。スキーマ生成整合性チェックと `git diff --check` 成功。
新規回帰: 結果再送の冪等性、通知失敗時の全体ロールバック、OFF保留/再反映、取消、3回lease timeout停止、再開による旧lease失効、他人の再開拒否、写真欠損、実snapshot復元、二重Listing防止、正本無効化/投影遅延、Owner移転と自己/旧Owner拒否。既存A→B→C/Admin別経路も成功。
UIはNodeのDOMテストで確認前非送信、revision付きPOST、Owned/Formerly Owned再取得、競合表示、SignOut破棄、採否理由の文字表示、再開確認、ReviewのON/OFF比較更新を確認。
途中、UIテストの簡易DOMセレクタがページ移動ボタンまで数えて失敗した。テスト側を実DOMの `li button` と一致させ修正、全75件成功。初回のsandbox localhost制限によるPython失敗は一時待受の許可後に解消した。
警告2件: `-p no:cacheprovider`に伴うcache_dir未知設定、Starletteのhttpx非推奨。検証失敗は残っていない。

この移行前段階ではブラウザ自動テスト・目視・実サービス受入は未実施だった。MacのComputer Useは以前 `Computer Use permissions are not granted` で拒否され、再試行していない。Playwrightの標準Chromiumキャッシュも未配置だった。DOMテストを実ブラウザ確認とは扱わない。

## 仮想PC上のレビュー修正（2026-10-06、未コミット）

移行後の独立レビューで見つかった5点を修正した。元の変更を保持し、同じbranchで作業。commit、push、配置、実データ操作、認証設定変更は行っていない。

- 保留回答を先に反映してから、結果提出・観察・画像取得・失敗報告の現行leaseと状態を再検証する。保留失敗で失効した旧leaseからClaimは作れない。明示的な本人再開後だけ新しいleaseを発行する。同一の確定結果の再送は冪等。
- 固定generation写真の欠損・破損・参照不備は当該申請だけerror停止し、次の有効申請を処理する。初回キュー先頭と保留採否の両方を対象にする。写真検証はClaim/通知書込み前に完了し、DB整合性・通知保存・権限・サービス障害は握り潰さずトランザクションをロールバックする。
- 所有状態を置き換えるAcquireのNegative判定では理由を検証・保存・通知する。画面は申請者への共有を示し、理由を含めて確認する。理由編集時は確認をやり直す。
- Specification/Repairの判定画面はspecification_kindとclaim_spec_itemsの全field/valueをテキスト表示する。既存入力上限内で返し、切り詰めた内容では承認させない。
- 再開POST中にEscape/Close/背景クリックで閉じても、同じアカウントの申請一覧を最新化し、ダイアログは再表示しない。SignOut/アカウント変更後の古い応答と、順序逆転した一覧応答は破棄する。

審査5点修正時の仮想PCaggregate結果: Python **900 passed**、JavaScript **95 passed**。依存定義/固定版/導入済みclosureチェック、PostgreSQLスキーマ生成整合性、git diff --checkも成功。既存Starlette/httpx非推奨警告1件。新しいサービス回帰は実SQLiteトランザクション＋in-processアダプタであり、実PostgreSQL検証の代替とはしない。

Owner判定・申請再開/中断・Review ON/OFFの実Chromium用journeyを追加し、browser runnerへ接続した。Python構文確認と申請再開fixtureの埋込みJavaScript構文確認は成功。この時点のCloud環境ではjourneyを実行していなかった。Cloud環境で先に確認されたChromiumのsocket拒否とPostgreSQLサーバー準備の制限を迂回せず維持する。この時点ではPostgreSQLの追加回帰も未実行だった。上のMacでの成功は移行前実装の記録。修正後の実ブラウザ/実PostgreSQL結果は次節を正本とする。

## 修正後の最終検証（2026-10-06、Mac利用を個別承認）

Cloud環境の既存制限を迂回せず、利用者が明示承認したMacで残っていたPostgreSQLと実ブラウザ検証だけを実行した。

- PostgreSQL **18.6**: Library checkpoint version 1の修正済みソースで、一時4DBの統合チェックが **exit 0**。審査・Owner・復元・その他既存統合の追加回帰を含む。
- 実Chrome **154** / Playwright **1.63**: browser runnerの全7グループが **exit 0**。Overlay部品、27種類の背景クリック/終了、ユーザーjourney、Cloud account、18件の申請再開/中断journey、Owner判定、Console Review ON/OFFを通過。
- 初回ブラウザ実行で、テストのリクエスト記録がmultipart PNGをUTF-8文字列として読んでUnicodeDecodeErrorになった。製品処理ではなく記録用fixtureを、post_data_bufferによるbytes保持とbytesによる認証入力漏出検査へ修正した。同じ2行をMacに同期してrunnerを再実行し、全グループ成功を確認した。
- このfixture修正に3件のPython回帰を追加。最終Cloud aggregateは **Python 903 passed / JavaScript 95 passed**。構文検証、依存整合性、PostgreSQLスキーマ生成整合性、git diff --checkも成功。既存Starlette/httpx非推奨警告1件。
- Mac検証終了後、テスト用PostgreSQL/アプリ/ブラウザの実行プロセスは残っていないことを確認した。

これは隔離した開発テストの完了である。実サービスのログイン・データ・写真の利用、staging/本番配置、Review ON、実データ審査、Cloud単独認証、審議担当の自動/定期起動は行っていない。commit・push・PR作成もない。ソースと開発資料の最終checkpointに37変更ファイルと適用patchを保存する。

## 仮想PCでの再現

認証情報やDBをMacからコピーしない。既存リポジトリのAGENTS.md、Claim設計不変条件、CLOUD_OWNERSHIP_REVIEW.mdを先に読む。

```sh
# GitHubから取得済みの、ベースcommitを含むcleanなclone内で
 git switch -c codex/cloud-review-ui 6e2d90138cfadb42e638272ca7c990021465242d
 git apply --check /path/to/unpacked/changes.patch
 git apply /path/to/unpacked/changes.patch
 git diff --check
```

アーカイブの `source/` は変更後ソースの照合用。patchには未追跡の新規ファイルも含む。MANIFEST.jsonの各ハッシュと照合する。Mac固有のvenv/configは使わない。

Python3.12以上、Node.js（node:test対応）、PostgreSQL18のinitdb/pg_ctl/psqlを用意する。Python依存はベースのapp/pyproject.tomlで管理。新しい依存追加なし。

```sh
python3 -m venv app/.venv
app/.venv/bin/python -m pip install -e 'app[dev,postgres,identity,storage,browser]'
PYTHONPATH=app/src app/.venv/bin/python -B -m pytest app/tests -q -p no:cacheprovider
node --test app/tests/test_*.cjs
PYTHONPATH=app/src app/.venv/bin/python -B app/tests/run_postgres_checks.py --postgres-bin /path/to/postgresql18/bin
PYTHONPATH=app/src app/.venv/bin/python -B scripts/build_postgres_schema.py --check
# 新しい仮想PCにブラウザを準備した後の追加検証
app/.venv/bin/python -m playwright install chromium
PYTHONPATH=app/src app/.venv/bin/python -B app/tests/run_browser_checks.py
```

Macでは既存venvのPython3.12、ChatGPT同梱Node、Homebrew PostgreSQL18を使った。PostgreSQLテストは非rootユーザーで一時クラスタを作る。rootの仮想PCでは非rootテスト実行ユーザーが必要。実行スクリプトは一時データのみを使うが、再現時も本番・stagingの接続環境変数を持ち込まない。

## 残件・運用待ち

1. 差分レビュー、追加DOM回帰、個別承認されたMacでの実PostgreSQL/Chrome自動検証は完了。実サービスでの利用者受入と手動目視はこの隔離テスト結果に含めない。
2. Admin用申請一覧/手動採否、一般TopPage統合、過去履歴ページ、写真公開同意/一般配信、非公開写真整理は後続。今回の対象を拡大しない。
3. 審議担当の自動起動/定期起動は未接続。アプリ側Review ONだけでは起動しない。Cloud単独認証も未確認。ローカル認証診断成功をPC不要のCloud実行完成とは扱わない。
4. ステージング配置、Review ON、実データ審議、所有申請の受入6項目は別途承認。現在の配置済み状態は更新していない。

## Mac権限の事実と後で閉じる対象

- 使用: 既存Googleログインの自動更新とreview専用SA短期IDトークン発行・指定診断先への送信を、明示承認の1回だけ実施。診断ok/google_oidc、queues_connected=false/data_changed=false。トークンを表示/アーカイブへ保存していない。既存gcloudキャッシュの更新は起こり得る。トークンのプロセス内保持終了はトークン即時失効を意味しない。
- 既存: gcloudログイン、専用SA、既存資料に記載された対象SAのOpenIdTokenCreator権限、Codexのygc_staging_review設定。今回新規IAM/SA鍵/恒久ログインは作成していない。現在のIAM状態の全監査は未実施。
- 使用: Macローカルのファイル読み取り・作業ディレクトリ編集、一時PostgreSQL/localhostテスト待受、プロセス終了確認。sandbox制限を越えるテスト/プロセス読取は各コマンド単位の自動承認レビュー経由。これをmacOSの恒久的なOS権限付与とはみなさない。
- 未許可: Computer Use。macOSの画面収録/アクセシビリティ/フルディスクアクセス設定は今回変更していない。ユーザーが別途許可した全設定はこの記録からは特定できない。
- Library: ソースだけを本人Libraryへ保存する明示承認あり。公開共有や他人への共有操作はしない。
- 権限解除/Googleログアウト/IAM削除は未実施。移行後、ローカルMCP無効化、gcloudの既存ログイン継続要否、SAトークン発行権限、OS設定を具体的に確認してから必要な対象だけ閉じる。開発仮想PCで認証情報を再利用しない。

## 全変更ファイル（仮想PC修正後、37ファイル）

- `app/src/ygc/cloud_account_api.py`
- `app/src/ygc/cloud_application_routes.py`
- `app/src/ygc/cloud_applications.py`
- `app/src/ygc/cloud_db_restore.py`
- `app/src/ygc/cloud_maintenance_job.py`
- `app/src/ygc/cloud_operations_routes.py`
- `app/src/ygc/cloud_owner.py`
- `app/src/ygc/cloud_owner_routes.py`
- `app/src/ygc/cloud_review.py`
- `app/src/ygc/cloud_review_gateway.py`
- `app/src/ygc/db/postgres_operations.py`
- `app/src/ygc/db/postgres_ownership.py`
- `app/src/ygc/static/cloud-account-applications.js`
- `app/src/ygc/static/cloud-account-guitars.js`
- `app/src/ygc/static/cloud-console-page.js`
- `app/src/ygc/static/cloud_console_html.html`
- `app/src/ygc/static/locales/en.json`
- `app/src/ygc/static/locales/ja.json`
- `app/tests/browser_cloud_applications_retry.py`
- `app/tests/browser_cloud_console.py`
- `app/tests/browser_cloud_owner.py`
- `app/tests/browser_user_journeys.py`
- `app/tests/postgres_operations_checks.py`
- `app/tests/postgres_review_checks.py`
- `app/tests/run_browser_checks.py`
- `app/tests/test_browser_request_capture.py`
- `app/tests/test_cloud_applications.py`
- `app/tests/test_cloud_applications_retry.cjs`
- `app/tests/test_cloud_owner_content.cjs`
- `app/tests/test_cloud_owner_content.py`
- `app/tests/test_cloud_owner_routes.py`
- `app/tests/test_cloud_review_controls.cjs`
- `app/tests/test_cloud_review_failures.py`
- `app/tests/test_cloud_review_gateway.py`
- `docs/history/HANDOFF_2026-10-06.md`
- `docs/history/VM_HANDOFF_2026-10-06.md`
- `docs/migration/CLOUD_OWNERSHIP_REVIEW.md`
