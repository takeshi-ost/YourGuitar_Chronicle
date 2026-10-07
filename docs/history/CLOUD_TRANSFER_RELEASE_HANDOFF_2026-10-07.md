# Cloud Transfer / Release 引き継ぎ

## 基点と作業範囲

- 対象：`takeshi-ost/YourGuitar_Chronicle`
- 正式な適用基点：`f0dd81504c4265e35b7bb62bfa4b2a7ffe472e83`（PR56統合済みmain）
- Cloud checkout：`feat/cloud-transfer-release`
- checkoutの親：`81ec34aabedb4752d17517d96f3c2c5973093ee7`
- 基点のtree：`ff49443292a9480d5d05986c1380b6397b2ce112`

GitHubの比較で81ec34aa→f0dd8150はmerge commit1件、変更ファイル0件と確認した。同じtreeからの変更であり、成果物patchはクリーンなf0dd8150へ適用する。Cloud内の既存Media checkoutは保持し、別checkoutで作業した。

このcheckpointは未commit・未push・未PR・未merge・未deploy。実ステージングの個体50件／Claim67件、Offline v13、Review OFF、autoCrawl OFFの境界を維持し、実DB・実受領・実写真・メール・認証・IAM・bucketは変更していない。

## 実装した内容

- Email確認済みのIdentity Platform principalとAccounts正本から本人を確定するTransfer/ReleaseのAPI。
- Current Owner限定の相手検索・Transfer申請・Release、参加者だけの一覧／詳細、ToのAccept/DeclineとFromのCancel。
- Account Owned/Formerly Ownedと公開Product Detailからの導線。本人のTransfer一覧から相手の提案を確認できる。
- 受領者ID・承認日時・承認時Current Owner IDのEvidence、合意状態、Verificationを区別した表示。
- 共有Repository/Observation/PostgreSQLフェンスの再利用。新規schema、移行、runtime権限追加なし。
- Ownership/Transfer revision、古い所有者画面、相手のBAN/無効化、係争ロック、サービスモードと重複・競合応答への対処。
- 通信結果不明では自動再送せず、最新状態を読み直してから明示的に次の操作を確認する画面。閉じる、戻る/進む、別個体、SignOutの古い応答を破棄する。

詳細仕様：[Cloud Transfer / Release](../migration/CLOUD_TRANSFER_RELEASE.md)。既存のprivate Media配信とOwner Verificationは別の権限経路を維持する。相手の名前／ID以外のプロフィール、メール、所在地、認証情報、合意EvidenceやRelease本文の一般公開は行わない。

## LOCALとの意味の一致

Transfer成立前は元Ownerを維持する。Acceptの再送でEvidenceや通知を重複させず、管理者のVerificationを上書きしない。受領者のPositive Transfer自己判定禁止と、A→B→Cの前段否定による連鎖取消をしない規則を維持する。

Releaseは共有の時系列規則に従う。過去日付のReleaseより後に所有根拠がある場合、Releaseを履歴へ記録してもCurrent Ownerは変わらない。この既存仕様を「常にUnknownへ変更する」新ルールへ置き換えていない。履歴だけが増えた場合もrevisionが変わり、同じ古い送信の重複を拒否する。受領がClaim順序により採用されないTransferは、受領の全変更を取り消す。

Inherit新規作成、Automation Lost、Incident / Lost、旧Transferを混同しない。係争中の停止は維持するが、係争開始・証拠・管理者裁定UIはこの単位に含めない。Releaseの一般編集/無効化、公開プロフィール、メール通知、公開ギャラリーも追加していない。

## 検証結果

最終checkpointでPython **1,367件**、JavaScript **421件**が成功（新規OwnershipのPython106件、JS58件を含む）。依存固定整合、PostgreSQL schema生成整合、diffチェック、追加受入スイートのcompile/importも成功。Pythonには既存TestClientとfixtureのHTTP送信APIの非致命的な非推奨警告2件がある。詳細は`manifest.json`と`validation.log`を参照する。

独立レビューで見つかった「通信不明後の再取得失敗による画面エラー」「古いアクセス再検査が新しい個体を消す競合」「新しい宛先の正本状態が作成結果revisionに含まれない競合」の3点を修正し、回帰試験を追加した。レビューの追加確認はPython210件・Node108件が成功。未解決の指摘はない。

実PostgreSQLとChromiumはこのCloudでは未実行。過去に拒否されたインストール／起動は再試行していない。追加したPGスイートはDB ownerでfixtureを作り、サービス操作は既存の制限付きruntime roleで実行する。権限を増やして通す仕組みはない。大きなID、本人/第三者の差、受領Evidence、再送、BAN、競合、故障時のrollbackを含む。

ブラウザスイートはproductionのAccount/Public assetsと認証アダプタを使い、すべての外部要求を合成fixtureで遮断する。実認証・メール・DB・ステージングは使わない。fixtureは未知の要求を失敗させ、ページ終了前に未処理要求を待つ。既存ブラウザfixtureも新しい静的moduleと空の本人Transfer一覧に対応させた。

## 次の受入と公開ゲート

同じcheckpointを許可されたMacまたは通常CIのクリーンなf0dd8150へ適用する。実ステージングへfixtureを投入しない。

```sh
python scripts/check_dependencies.py
python scripts/build_postgres_schema.py --check
python scripts/run_tests.py --browser --postgres-bin /path/to/postgresql18/bin
```

CIのループバックPostgreSQLサービスを使う場合は`--postgres-port 5432`。PG/ブラウザ未実行を合格と表現せず、同じ最終treeで成功を確認する。元Ownerからの申請→宛先の受領→Owned移動、Release→Formerly Owned、受領直後のOwner Verification、private Media旧Ownerの拒否を確認する。

Macでのcommit/push/PR/merge/deployや、本番/ステージングの実受領はそれぞれの承認後。実データへの受領はこの受入に不要。今回のcheckpointだけを適用し、既存のMacの未確定変更・DB・写真・環境設定を上書きしない。
