# Cloud Admin申請管理: 2026-10-07 引き継ぎ

## ソースの状態

- Repository: `takeshi-ost/YourGuitar_Chronicle`
- 正確なbase: `7e47c3fc921f1a76e8515aa037f5f5d080afbcdf`（PR #52統合後main）
- 作業branch: `feat/admin-application-review`
- 変更は未コミット。push、PR、merge、deploy、サービス設定変更、実申請の採否、実モデル審議なし。
- Cloudで新しいclean checkoutから実装。以前の作業用checkoutとそのdirty変更は保持。

## 実装

Cloud ConsoleにOwnership applicationsの検索・種別/状態絞込・ページ送り、詳細・非公開写真・AI観察/元診断/管理履歴、理由と表示時versionを要求する採用/不採用/再審議/取消を追加した。
既存の`acquire_review`管理判定をトランザクション内で再使用し、新しい採否ルールは導入しない。

Accounts正本の有効Adminを処理時にも確認し、maintenance/Crawl mutex・投影・Chronicleのロックを保持する。CSRF対策としてbearerのみ・JSONのみ・cross-origin拒否、cache禁止、写真の認証付きバイナリ配信を維持する。Storage参照やlease tokenを返さない。
Listingは一度だけ個体/Claimを作る。Acquireは現在OwnerがユーザーならUnverifiedで承認待ちとし、通常Ownerの自己判定禁止・移転後の権限喪失・Owned区分は既存評価器へ委ねる。不採用は既存ClaimをNegativeとして再評価し、再採用は同じClaimを使う。Claim強制Verificationは既存Guitar管理経路と分離する。

Review OFFはworker実行/回答反映の停止であり、明示的Admin操作を止めない。管理操作は古いleaseを失効させる。保留回答はlease tokenを除いて管理履歴へ保存した後に削除し、削除が遅れても旧回答が採否を上書きしない。
再審議では途中の独立観察、元レポート、エラーも履歴へ保存する。壊れた写真参照でも詳細を閲覧し取消/不採用にできる。期限切れ下書きをGETで更新せず、開始操作時に期限切れAcquireのactive unique slotを解放して新しいChallengeで再申請できる。
申請者の画面では、管理者の採否理由と元AI理由を別表示する。

## 手動runtimeの実装範囲

Consoleには外部MCPの一回実行手順と、現在のReview ON/OFF・processing・lease期限・試行数・保留回答の種類/時刻・最終結果を実データAPIから表示する。
Consoleのボタンからモデル/Mac/Cloudタスクを起動するdriverは追加していない。新しいAPI・課金・秘密鍵・IAM・常時実行も追加していない。

既存Macの`ygc_staging_review`を許可された別セッションで一回手動利用する手順は[運用仕様](../operations/cloud-application-administration.md)にある。
実モデルE2Eには、使用する既存MCPセッション、対象の試験申請/写真、Review ONへの一時切替、審議結果によるClaim/個体の作成、必要なOwner本人の応答を別途承認して実行する必要がある。接続診断やモデル起動は今回実行していない。

## 最終検証

最終製品コードに対する`python scripts/run_tests.py`:

- Python **1,050 passed**（既存Starlette/httpx非推奨警告1件）
- JavaScript **166 passed**
- aggregate exit 0、テスト用一時保存先の削除完了
- `scripts/check_dependencies.py`: 成功
- `scripts/build_postgres_schema.py --check`: 成功（スキーマ変更なし）
- `git diff --check`: 成功
- 新PostgreSQL/ブラウザテストの構文・import確認: 成功

Pythonには本物の隔離SQLiteトランザクションを使う状態遷移テストが含まれるが、PostgreSQLの代替とはしない。
NodeのDOMテストは実Chromiumの代替とはしない。
既知のCloud制限を再試行せず、実PostgreSQL・Chromiumは今回未実行。実サービス受入・目視・Review ON・実モデル審議も未実施。

独立レビューで見つけた3項目（壊れた写真メタデータで取消まで失敗、期限切れ下書きの誤競合、再審議で途中/保留観察を失う）を修正して回帰を追加した。

## Mac等の許可環境で残る検証

アーカイブの`MANIFEST.json`とSHA-256を確認する。新しいclean checkoutにbaseを用意し、既存作業や認証設定を上書きせず適用する。

```sh
git switch -c feat/admin-application-review 7e47c3fc921f1a76e8515aa037f5f5d080afbcdf
git apply --check /path/to/checkpoint/changes.patch
git apply /path/to/checkpoint/changes.patch
git diff --check
PYTHONPATH=app/src /path/to/python scripts/run_tests.py
PYTHONPATH=app/src /path/to/python scripts/run_tests.py \
  --browser --browser-executable /path/to/existing/Chrome \
  --postgres-bin /path/to/postgresql18/bin \
  --browser-artifacts /path/to/disposable-diagnostics
```

MacのPython/Node/PostgreSQL/Chromeパスは選択した環境で確認し、上のplaceholderをそのまま実行しない。
既存依存を使う。新しい依存追加なし。production/staging接続変数、Google認証、実DB、実写真をテストへ持ち込まない。

新チェックは`postgres_admin_application_checks.py`（本物の正本/投影/排他、並行重複Listing、Owner移転/巻戻し、通知失敗全体rollback等）と`browser_cloud_admin_applications.py`（実overlay・遅延応答・重複確認・終了/SignOut・写真URL解放等）。既存runnerへ接続済み。
実Chromeでの日英表示・狭い画面・操作の目視も確認する。

## 公開前

残る実環境テスト結果と差分を確認してから、commit/push/PR/merge/deployは利用者の新しい承認で行う。
このcheckpointに含むのは変更ソース、patch、検証ログとこの説明のみ。認証情報・DB・写真・venvを含めない。
