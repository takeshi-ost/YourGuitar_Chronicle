# Private dispute storage: rollout / recovery gates

2026-10-07。これは実装と適用計画。live／stagingのDB、GCS、IAM、Job、Webにはまだ変更していない。実際の公開、migration、配置、backup／restore実行はそれぞれ承認範囲を確認してから行う。

## 変更の意味

- 新規Evidence原本だけを既存private content bucketの固定generationへ保存する。
- Chronicle 003はreference tableと整合性triggerを追加するだけ。既存BYTEAやEvidence履歴を変換・削除しない。
- 原本には新しい期限・自動削除・公開URLを設けない。DBやGCSの応答が不明なoriginalは、未参照と思われても保持する。
- ローカルSQLiteは従来のinline保存のまま。Cloudの新規添付はGCS設定がなければ拒否する。
- 新WebはChronicle v3なしでは起動／ready成功しない。旧imageはv3を知らないため、単純なimage rollbackを復旧手段として扱わない。

## Gate 1: ソースと隔離検証

1. exact baseとcheckpoint manifestの全SHA256を照合する。元のworkflow ZIPはそのまま保持する。
2. portable Python／Node aggregateを実行する。
3. 許可済みMacまたは通常CIの使い捨てPostgreSQLで、v1／v2→v3、途中失敗rollback、再実行、既存runtime grants、新trigger、legacy／GCS混在quota、private evidence、CAS／同時操作、unknown commitと原本保持を実行する。
4. 同環境のChromiumで本人／Adminフロー、容量preflightエラー、stale auth／navigation／unknown responseを確認する。
5. fake storageだけでは実GCSのIAM・generation・CRC・latency・512 MiBの負荷条件を保証しない。実環境の検証は別承認後に行う。

## Gate 2: 変更前の読み取り専用preflight

この段階も本チェックポイントでは未実行。

新しいcodeを含むIAM専用backup Jobで、明示プロジェクトと `--target=chronicle --preflight-only` を使う。Jobがまだ旧imageの場合、先に別途承認されたimage更新が必要。既存Jobの既定引数やスケジュールを勝手に変更しない。

例となるJob引数（実行済みではない）:

```
-m ygc.cloud_backup_job --confirm-project=your-guitar-chronicle-staging --target=chronicle --preflight-only
```

このmodeはknown v1／v2／v3を読める。DBはread-only snapshot、GCSは存在するreferenceの固定世代GETだけを使い、archive upload、台帳追加、migration、原本変更を行わない。出力は件数・長さのaggregateと安全なstatus／codeに限定し、Evidence、ID、filename、object name、credentialを出さない。

成功が示す範囲は、そのsnapshotが現行restore容量に収まり、dispute originalsを検証できたこと。実restore、他種のmedia、全サービスの稼働、将来の容量を保証するものではない。変更前には別途、実際の保護用backup保存／読み戻しを確認する。

### 失敗時に進めてはいけない条件

- `legacy_evidence_line_limit` / `legacy_evidence_restore_limit`: 既存BYTEAが保守的なline／restore予算を超える。既存DBと原本とbackupを保持して停止。新GCS保存へ切り替えただけで解決したとは扱わない。別途承認されたarchival recoveryまたはlegacy移行計画が必要。
- `chronicle_restore_capacity`: Chronicleの新しいsnapshotが32 MiBのrestore-ready staging予算を超える。従来のMAX_RAW=128 MiBや他DBの保存上限を変更してはいないが、新しいChronicle保存を復元可能な成功とは記録しない。
- `snapshot_line_limit` / `snapshot_raw_limit` / `snapshot_compressed_limit`: 既存8 MiB／128 MiB／25 MiBの制限超過。上限を無断で広げず、別のbounded recovery方針を決める。
- original generation／size／MIME／hash不整合: 参照先を最新世代で代用しない。DB参照を消して通過させない。元のimmutable generationの保全・復旧を確認する。

## Gate 3: 承認後の適用順序

1. 現在のmode、Review／Crawl／backupスケジュール、稼働image digest、schema version／checksum、公開headを再確認する。以後の操作は承認されたmaintenance windowで行い、既存のOffline／停止設定を意図せず変更しない。
2. Gate 2と保護用backupを確認する。新しいbackup／maintenance codeは旧v1／v2を読む互換性を持つ。
3. 現行が検証済みChronicle 002であることを確認し、schema ownerで既存の明示migration入口から未適用の003を適用する。この入口は全pending revisionを順に適用するため、現行が001の場合は停止し、002＋003のchainを別途確認・承認する。Web runtimeにDDL権限を付けない。実行はtransaction内で、SQLとmanifest hashの完全一致を検証する。
4. migration完了後、Chronicle v3／43業務table／累積checksumを確認する。原本BYTEAが不変、新reference tableが想定どおりであることを確認する。
5. v3を読むすべてのconsumerを同じ検証済みsourceの対応imageへ更新する。Webだけでなくbackup、schedulerのbackup worker、maintenance、account projection、Crawl／reviewなど、対象環境に実在するconsumerを一覧化する。旧imageはunknown schemaとしてfail closedし得るため、混在を正常稼働と扱わない。
6. 許可されたsynthetic受入で、匿名拒否、現在権限の本人／Admin原本取得、private/no-store、GCS固定世代、保存／読み戻しとrestore preflightを確認する。本物の係争の判断はしない。
7. 新規Chronicle backupの原本参照検証とread-back成功を確認する。既存のmode、Review／Crawl／schedule状態を再確認し、別の明示指示なしに自動処理をONにしない。

## Recovery / rollback

- 003がcommit前に失敗: migration transactionはtable、trigger、grant、schema version更新をまとめてrollbackする。既存データと001／002は不変。原因を確認し、同じ検証済みmigrationを再実行できる。
- 003がcommit済み: schemaとreferenceを保持する。自動down migration、table drop、checksum書換え、inline BYTEAへの逆変換をしない。復旧はv3を理解する修正版imageを使うforward recoveryを基本とする。従来imageへの単純rollbackは未知schemaで停止し得る。
- upload結果が不明: DB操作は成功と表示しない。objectが保存済みかもしれないため削除しない。現在case／round／versionと履歴を読み直し、明示的に次の操作を判断する。
- DB commit結果が不明: referenceがcommit済みかもしれないため、objectを保持する。旧CASの再送で新しいEvidenceを作らない。
- 旧v1／v2 archiveのv3 restore: 既知checksum／columnsだけを認め、追加tableを空として補い、最新Accountsからprojectionを再構築する。v3 snapshotは旧schemaへ復元しない。
- restore／resetやbackup pruningでDB referenceまたは古いarchiveが削除されても、Evidence original objectは削除しない。古いbackupや不明commitが参照している可能性を残す。
- locked-owner BANのprojection停滞と256-round／1024-eventのbounded readerは従来checkpointの運用条件として残る。今回のstorage変更で所有権のlockを緩めない。
