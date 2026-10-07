# Cloud Ownership Disputes 作業引継ぎ

2026-10-07。これは非公開係争workflowと、追加承認されたGCS原本／DB移行実装をまとめたローカルcheckpoint。実engine検証と実環境preflight、別途の適用承認を経るまでrelease-readyとは扱わない。

## 正確な基点

- 基点main: `8c2f15ad34ae3ac0f37243b15e058efb76510f24`
- 基点tree: `0154fb2e06105607b8773fe83dd52ac6e3e812a8`
- ブランチ: `feat/cloud-ownership-disputes`
- PR #60通知機能までmergeされたmainをread-onlyで照合後、別checkoutで開始。以前の通知checkoutは保持。
- commit、push、PR、merge、deploy、schema適用、IAM、実データ変更、実人間の裁定は未実施。

## 実装内容

本人の申立て候補、Decline理由確認と明示的受理、初回Appeal、既存案件参加、ラウンド単位の証拠提出と非公開添付、確認済み要旨、Admin裁定／追加資料要求／再審議を既存ルールで接続した。Adminは既存のroleだけを使用する。

通知既読は係争判断と分離。導線は最新の当事者権限を検証して開く。元通知にcase_idがない履歴では、対象案件が曖昧な場合リンクを推測しない。

共有ローカルstate machineは維持し、accepted applicationのrequest_kindをAcquireへ明示限定、Adminの実actorを監査／イベントへ渡す引数を追加した。旧ローカル呼出しの既定動作は維持。

詳細とAPIは明示DTO allowlist、文字列BIGINT、plaintext、private/no-store。原本・説明・未公開要旨は提出本人／Adminのみ。別申請者の証拠は共有しない。書込にはcandidate revisionまたはcase version＋roundのCASを使い、不明応答は再読込と明示的再操作を要求する。

詳しい境界は`docs/migration/CLOUD_OWNERSHIP_DISPUTES.md`を参照。

## 追加承認されたstorage / DB移行の実装

- 新しい添付原本は既存private content bucketへcreate-onlyで保存し、固定generation／size／MIME／SHA256を新tableへ記録する。本人とAdminの現在権限を検査して取得し、refやURLを応答へ出さない。
- `chronicle_003.sql`はadditive migration。既存001／002は不変、legacy BYTEAは変更・削除・自動変換しない。
- 新tableは`ownership_dispute_originals`。Evidenceとの二重原本とMIME不一致を拒否し、ref更新および原本のauthor／Claim／case再割当てをtriggerで拒否する。通常の確認要旨公開は維持する。
- 1件12 MiB／100提出／案件256 MiBは維持し、BYTEA＋GCS合計でquotaを検査する。失敗／不明upload・commitでも原本を削除しない。
- backup保存／read-back／verify-onlyとrestoreで固定世代とhashを確認する。restoreは最初の破壊的DB操作前に全originalを検証する。old v1／v2 archive→v3だけに明示的なadditive互換経路を用意した。
- `cloud_backup_job --target=chronicle --preflight-only`はread-onlyで旧BYTEA容量とsnapshotのrestore容量、dispute originalsを検証し、安全なaggregateとcodeだけを返す。
- SQL003 SHA256: `9f66de2b3b41d33341173891c11c8c7c3da87ef8657d60666b8e6d58f6fabf17`
- Chronicle v3累積checksum: `0d2fcd9f4de77aeaa041a413cbbf85e43af4c05ac527db827b53a6d1b5ad56ab`

適用順序・全consumer image整合・失敗時の保持・forward recoveryは `docs/migration/CLOUD_DISPUTE_STORAGE_ROLLOUT.md` を参照。

## 公開前の未解決条件

1. 既存のoversized BYTEAがあるか実環境preflightは未実行。新規GCS保存は大きな原本をDB archiveから分離するが、既存BYTEAを自動修復しない。該当時は証拠提出をsafe409で停止し、別の明示承認されたarchival recoveryを行う。backup上限は既存8 MiB／128 MiB／25 MiB、restore32 MiBのまま。新規Chronicle保存はrestore-ready32 MiBを超えれば安全な専用codeで拒否する。
2. 実PostgreSQLとChromiumの追加acceptance suiteはCloud制限により未実行。通常CIまたは許可済みMacで実行する。過去のsocket／install拒否は再試行・迂回していない。
3. locked ownerのBAN／Silent BANで既存のOwner固定triggerがAccounts projectionを拒否した場合は、receiptを更新せず全操作をfail closedにする。優先規則を変更せず運用上の復旧判断を残す。
4. 詳細は256ラウンド／1024履歴までのbounded reader。超過はtruncateせず拒否し、結果detailを生成できないmutationはcommit前rollbackとなる。長大履歴のcloud操作継続にはhistory paginationが必要。

UIの入口はAccount／Admin Console／通知に限定。public Product DetailのDTOにprivate係争の有無を混ぜないため、当事者専用Under dispute badge／詳細導線は後続のauthenticated hintとして残る。サーバー側の所有操作lockは継続する。

保存期限短縮、証拠削除、第三者の新規参加、自動督促、追加期限、無回答自動移転、メール／push追加は含めない。

## 検証

初回workflowのみの保存済みcheckpointはPython 1,792件／JavaScript 757件が成功。追加storage版の最終共通検証件数は末尾とmanifestへ記録する。追加後のdispute Node suiteは78件。最終件数とlogはcheckpointの`manifest.json`、`validation.log`を正とする。Python／Node共通検証を実行し、synthetic fixtureだけでprivate service／HTTP／既存係争回帰を検証する。独立reviewで原本privacy、正本権限、CAS、bounds、Console失権時の消去を確認する。

PG suiteは`app/tests/postgres_dispute_checks.py`と`app/tests/postgres_dispute_storage_checks.py`、Chromium suiteは`app/tests/browser_cloud_ownership_disputes.py`。いずれも共通runnerに登録し、compile／importを確認する。compileと実engine実行を混同しない。Known TargetClosed cleanup警告はこの変更の修正対象外。

## 再開方法

許可済み環境で上記baseのclean checkoutへ`disputes-storage.patch`を適用し、`manifest.json`の全file SHA256と照合する。既存DB・画像・設定・未確定変更を上書きしない。公開前条件が解決し、追加変更を含むPython／Node／Chromium／PostgreSQLの全検証が成功してから、別途承認された公開手順へ進む。

大きなGitHub create_tree本文が停止した履歴があるため、公開承認を得た後はsmall blob作成・検証とSHA-only treeを優先する。この引継ぎは公開の承認を意味しない。

## 保存済み初回checkpointの保全

初回workflow ZIPは変更せず保持。SHA256は `80bbbd2578156fb15611134a40fed85c11e6586c4699d37c73007a8a217038f6`。storage版は別ZIP／manifestで提供する。両方のpatchを重ねず、どちらも明記された同じmain基点へ適用する。

## 追加storage版の最終検証

最終共通検証: Python 1,888件、JavaScript 758件成功、失敗0。独立post-freeze focused検証102件成功。全Python compile、PG／Chromium suiteのsocket・DB・subprocess起動を禁止したimport、diff checkを確認。実PG／Chromium／GCS／実migrationは未実行。patchは基点archiveへ適用し直し、全manifest hashを照合してからpackagingする。
