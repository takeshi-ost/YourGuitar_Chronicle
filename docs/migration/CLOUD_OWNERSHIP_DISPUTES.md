# Cloud Ownership Disputes: private workflow checkpoint

2026-10-07。`8c2f15ad34ae3ac0f37243b15e058efb76510f24`を基点とするローカル実装段階。公開、PR、merge、deploy、実案件の裁定、IAM変更は行っていない。

## 保存方式と公開前条件

最初のworkflow checkpointで発見したBYTEA／バックアップ容量の不整合に対し、利用者の追加承認を受けて非公開GCS原本＋Chronicle migration 003の実装を追加した。実環境への移行・配置は未実施。

- 添付1件12 MiB、1案件100提出、添付合計256 MiBを維持。合計は既存BYTEAと新しいGCS原本を合わせて計算する。
- 新しい添付は既存のprivate content bucketへcreate-onlyで保存し、DBには固定generation、size、MIME、SHA256を保持する。新規添付のBYTEA fallbackはない。
- 既存BYTEAは変更・削除・自動変換しない。提出本人とAdminは引き続き取得できる。
- DB snapshotの既存定数は1行8 MiB、展開後128 MiB、圧縮25 MiBのまま。復元の展開後32 MiBも変更しない。
- 新規Chronicle保存には、復元可能性の明示preflightとして32 MiBを超えた時点で `chronicle_restore_capacity` を返し、成功台帳を作らない。既存の128 MiBまでのarchive検証や、他DBの保存上限を引き下げない。
- 12 MiBのlegacy BYTEAはBase64だけで16,777,216 bytesとなる。新しい保存方式だけでは、そのような既存データの保存は直らない。BYTEAをロードしないlength集計で保守的な上限を検査し、該当データがあれば `legacy_evidence_line_limit` または `legacy_evidence_restore_limit` で停止する。
- 既存BYTEAの容量preflightが失敗する間、新たな証拠提出は明示的に停止する。参加者にはprivateな件数・サイズを返さず、管理者による保存確認が必要な旨を表示する。現在データ／原本／既存バックアップは保持する。
- 保存期限・自動削除・bucket sweepは追加しない。GCS uploadまたはDB commitの応答が不明な場合を含め、新しいoriginal objectを失敗cleanupで削除しない。未参照の可能性があるobjectも残り、その保管費用は発生し得る。整理は別途承認された作業とする。

## Additive migration と互換性

`db/postgres/chronicle_003.sql`は `ownership_dispute_originals` を追加する。`evidence_id` を既存Evidenceへ紐付け、private objectの固定世代、サイズ、種類、ハッシュと作成時刻を保持する。既存001／002とローカルSQLite schemaは書き換えない。SQL checksumと累積schema checksumを既存manifest機構で検証する。

reference更新はDB triggerで拒否し、BYTEAとの二重原本、種類の不一致も拒否する。DB参照の削除は正規のrestore/resetに必要なため許可するが、GCS原本の削除にはつながらない。runtimeの既存CRUD権限モデルの範囲内で、新規IAM、bucket、公開URL、認証grantは追加しない。

新Webはstartupとreadyで既知のChronicle v3を検査する。runtimeがschemaを作成・移行することはない。旧v1／v2 archiveからv3への復元は、既知checksumと完全なカラム一致を確認し、新規reference tableを空として補う専用の互換経路だけを使う。v1では既知のprojection receipt tableも空として補い、最新Accountsから再構築する。任意版・未来版・不一致checksum・v3から旧版へのdowngradeを許可しない。

## Backup / restore の原本検証

Chronicleの保存、保存後のread-back、verify-onlyはarchiveのhash／schemaに加えて、全dispute originalの正確なgeneration、size、MIME、SHA256を検証する。DB archiveに原本本体を複製しない。存在しない世代や不整合referenceがあれば成功として記録しない。

復元は現在のAdmin／modeを再確認し、既存の保護用バックアップを維持する。archive内のoriginalとEvidenceの対応・重複・二重原本を検証し、指定世代の取得とhash確認を済ませてから、最初のDELETE／INSERTへ進む。世代が失われていればデータ置換前に停止する。backup pruningとresetはoriginal objectへ触れない。

実際のPG migration／GCS／restore検証と容量preflightは未実行。正確な適用順序、失敗時の保持事項、実環境の承認ゲートは `docs/migration/CLOUD_DISPUTE_STORAGE_ROLLOUT.md` を参照。

## 既存ルールの移植

`docs/features/OWNERSHIP_DISPUTES.md`と共通`disputes.py`の意味を維持する。

- 画像審議通過済みのAcquireで、承認すれば実際のObservationがCurrent Ownerを置き換えるものだけが候補。
- Declineの理由を確認して明示的にAccept decision、またはAppealを選ぶ。通知既読はAccept decisionではない。
- 無回答は既定14日後に申立て可能。無回答による所有権の自動移転、追加期限、自動督促、第三者受付、メール送信は追加しない。
- 初回申立ては説明、相手に示す要旨、添付を必須とする。既存競合Acquireは同じopen案件のcollecting中に参加できる。
- 各ラウンド、各Acquireの申請者と原Ownerはそれぞれ1回提出できる。追加ラウンドの添付は任意。全員提出後にreviewingへ進む。
- Adminの理由付き裁定は未提出者がいても可能。次ラウンドの追加資料要求はreviewing時だけ。決定は既存Admin VerificationとObservationで再評価し、期待するOwnerと一致しなければ全体を戻す。
- 解決した対象Claimは通常の編集・削除・Verificationからロックしたまま。後のOwnerへのTransferを巻き戻すような古い案件のreopenはしない。

## 認証・権限・競合

入口は毎回verified Bearerを検証し、issuer／subject／tenantからAccounts正本のapp_user_idを解決する。呼出側のuser_id、role、viewer_id、Cookieは権限に使わない。

操作は既存のmaintenance lock、service mode、canonical account／参加者lock、content projection fenceの順序で保護する。公開側のOwnerと係争の原Owner・申請者を再確認する。通常ユーザーはread_onlyでは読むだけ、offlineではアクセス不可。Adminは既存の独立した管理経路とmode契約を使い、新たなrole付与は行わない。

Decline受理／新規申立てにはClaim・Decline・所有状態を含むrevision、既存案件の提出とAdmin操作にはversionおよびround_numberを要求する。失われた応答の自動再送は行わず、新しい状態を読み直して明示操作する。古い入力から同じ証拠や決定を重複保存しない。

原OwnerがBAN／Silent BANとなってObservationのOwnerが変わる場合、既存のopen案件Owner固定triggerがaccount projectionを拒否することがある。この状態ではprojection receiptやSnapshotを先へ進めず、当事者／Admin操作をfail closedとする。係争lockまたはBANの優先規則を緩める変更は含めない。これは既存境界の運用上の復旧条件として残る。

## 非公開EvidenceとHTTP境界

- 原本、説明、未公開要旨は提出本人とAdminだけ。相手側にはAdminが確認・公開した要旨だけを返す。別申請者のEvidenceは返さない。
- detailはBYTEA本体やGCSのreferenceを返さない。添付取得だけが現在権限確認後に対象1件を読む。固定generationのGCS取得中もcanonical account／mode／projection fenceを保持する。
- 応答は1案件100 Claim／Evidence、各ラウンド200当事者、256ラウンド、1024履歴の読取budgetで制限する。超える既存履歴は黙って切り詰めず、detailをfail closedにする。変更後detailの生成もcommit前に行うため、このbudgetを超える変更はrollbackとなり、cloud操作の実効上限にもなる。保存済み履歴は削除せず、既存の再審議ルールは維持するが、長大履歴で操作を続けるには別途history paginationが必要。
- multipartはdata JSONと添付最大1件。ストリーム、part、headerに別々の上限を置き、成功・失敗・切断・不完全なformでもspoolを閉じる。
- 入力はキーallowlist、UTF-8として扱えるplaintext、長さ、重複キー、decimal-string ID／version／roundを検証する。未知フィールドや呼出側identityは拒否する。
- 静止画像は既存処理でEXIF除去してJPEG化。PDFはdownloadとしてだけ返す。個人の元filenameは保存名に使わない。
- 応答は明示allowlistと文字列BIGINT。すべてprivate/no-store、Vary Authorization、nosniff、same-origin。添付は固定filename＋attachment、sandbox CSP。
- public media、gallery、外部URLへの公開、他者への原本共有は追加しない。

## API

participant prefixは`/api/auth/ownership-disputes`、Admin prefixは`/api/auth/admin/ownership-disputes`。

- GET participant prefix: 本人の案件一覧。GET `/options`: 候補一覧。いずれもafter／limit、既定25・最大50。
- GET participant `/options/{claim}`: 現在の候補とrevision。POST `/options/{claim}/acknowledge`: revision付き明示受理。
- POST participant `/options/{claim}/evidence`: multipart data JSON＋任意添付。新規申立てはcandidate revision、既存案件はcase_id／version／round_numberを送る。
- GET `{prefix}/{case}`: 現在権限で絞った詳細。GET `{prefix}/evidence/{evidence}/attachment`: 提出本人またはAdmin専用原本。
- GET Admin prefix: open／resolved／all案件一覧。POST Admin `/evidence/{evidence}/publish`: 確認要旨。POST Admin `/{case}/decision`: owner／applicant／request_evidence／reopen。

新旧の通知型は維持する。Decline通知の導線は現在の申請者権限を調べ、対応案件があればその案件へ進む。ownership_dispute通知は既存履歴にcase_idがないため、当人が開ける案件がその個体に1件だけの場合にリンクする。複数案件で曖昧なら推測せず本文表示のままとする。画面でも遷移後に最新の権限を再確認する。

このcheckpointのUI入口は本人AccountとAdmin Console、現在権限を確認した通知導線。public Product Detailの公開DTOへprivateな係争有無を追加しないため、ローカル版の当事者専用Under dispute表示／詳細導線はまだ移植していない。将来の追加はauthenticated hintを別途設計する。表示の有無にかかわらず既存のサーバー側所有操作lockは有効。

## 検証と公開ゲート

synthetic fixtureだけを使用する。Python／Nodeの共通検証、private HTTP境界、既存ローカル係争回帰を実行する。実PostgreSQLとChromiumのsynthetic acceptance suiteを共通runnerへ登録する。

このCloud環境では既存のPGインストール／Chromium socket制限を再試行・迂回しない。許可済みMacまたは通常CIで実engine検証を別途行う。PG／Chromium未実行を成功として記録しない。公開前には追加migration／storage／backup変更を含む全engine再検証、実環境のlegacy preflightと別途の適用承認が必要。
