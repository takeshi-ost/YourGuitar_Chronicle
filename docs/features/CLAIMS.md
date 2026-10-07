# 個体とClaimの機能仕様

対象：現行ローカル実装。概念・不変条件は[Claim中心の設計](../architecture/CLAIM_CENTERED_ARCHITECTURE.md)、物理的な保存先は[DB構造](../architecture/DATABASE_STRUCTURE.md)。


- Claimの投稿者、ユーザーに紐づく所有者、Transferの譲渡人・譲受人の名前はUser Profileへリンクする。カード・詳細ポップアップとBrowser Consoleで共通。IDを持たない外部掲載の名前や自由記入の旧所有者名はテキストで表示する。

- 新しいギターを登録できる。手動登録も外部収集も、Listing Claimを起点とする同じ個体作成パイプラインを通る。個体の現在のMaker / Model / Finish / Year / Serial、Owner / LocationはClaimから作るSnapshotを表示する。
- OwnershipはAcquire / Transfer / Releaseというタグを持つ一つのClaim種別。AcquireはOwnerとLocationを設定し、Releaseと旧TransferはUnknownに戻す。新規TransferはCurrent Ownerが相手ユーザーを検索して申請し、相手のAcceptをEvidenceとしてObservationが所有者を移す。承認者ID・承認日時・承認時点のCurrent Owner IDを保持する。合意とVerificationは独立する。成立済みTransferは承認時のEvidenceに基づく独立した所有権根拠として時系列順に適用する。過去のTransferの否定によって後続を連鎖的に無効化しない。譲受人自身はPositiveなTransferのVerificationを変更できない。詳細は [TRANSFER_CLAIM.md](../features/TRANSFER_CLAIM.md)。
- Specification / Repair / Incident（Damage / Lost / Theft）/ Event（Exhibition / Performance / Recording / Auction / Other）/ Media（画像）Claimを追加できる。本人が現在Ownerなら本人のClaimをPositiveにし、第三者の対象ClaimはUnverifiedから開始する。Current Ownerは通常判定の対象となる他ユーザーのClaimだけをPositive / Negative / Unverifiedに変更できる。自己Claimと自身の所有根拠となるPositiveなTransferは通常判定できない。管理者の強制判定は別経路。Identity CorrectionはListingの訂正入口から作り、重複を検査する。
- 元Ownerを主張するFormer Owner操作はAcquire / Releaseのペアを作り、Owner Verificationに従う。Claimの無効化は来歴を残すソフト削除。通常の表示とSnapshot評価から除外する。Listingは通常編集しない。
- ClaimにGood / Bad投票とResponseを記録できる。Media Claimの画像とEvent Claimの任意画像は一つのClaimに最大10枚、JPEG / PNG / WebP / GIF、画像ごと最大12MB。ギャラリーに反映する条件はClaimの有効性と承認状態に従う。アップロード画像は画像枠やサムネイルから共通アルバムで開き、矢印・左右キーで移動する。Reverbの掲載画像は外部掲載へのリンクとして扱う。
- 所有権や個体照合に争いがある場合、現在値が履歴そのものを消すことはない。詳しい規則は [CLAIM_CENTERED_ARCHITECTURE.md](../architecture/CLAIM_CENTERED_ARCHITECTURE.md)。

Ownerの決定経路は[Ownership Decision](OWNERSHIP_DECISION.md)のフローチャートを参照。

## Cloud移植

Specification / Repair / Incidentの本人投稿・編集・無効化とOwner判定への接続は[Cloud Claim投稿・編集](../migration/CLOUD_CLAIMS.md)を参照。ローカル全機能のクラウド移植ではなく、公開データ境界を拡張しない単位。
