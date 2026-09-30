# ユーザー間Transfer Claim

2026-09-30、`feature/observation-redesign`。ユーザー間の所有移転を、Fromの申請とToの合意Evidenceで表現する。Current OwnerとSnapshotを直接変更せず、Observationの評価結果に従う。

## 確定した仕様

- Fromは作成時のCurrent Owner本人で固定。Toはユーザー検索で指定する。他人をFromとして申請できず、自己移転も不可。
- 新規TransferはOwnership ClaimのTransferタグ、`ownership_source='user_transfer'`で記録する。未承認時はUnverifiedで、移転日も未設定。Owned / Formerly Ownedの変更は行わない。
- ToにTransfer通知を送り、本人だけがAccept / Declineできる。Fromは未成立の申請をCancelできる。第三者はこれらの操作を行えない。
- Accept時のEvidenceは**承認者ユーザーID・承認日時・承認時点のCurrent Owner ID（From）**の3項目。他のEvidence・写真・日付入力を要求しない。
- Accept時にFromが引き続きCurrent Ownerで、双方のアカウントが利用可能であることを再確認する。承認日時が移転日時となり、ClaimはPositiveで開始する。Toのプロフィールの所在地を新しいLocationとしてObservationが採用する。
- 合意とVerificationは独立する。Negative / Unverifiedは合意の撤回やDeclineではなく、Claimの現在の採用状態を変える判定。保存した合意Evidenceとaccepted状態は保持する。
- Verificationは既存規則を維持する。成立後のToはCurrent OwnerとしてFrom作成のTransferを変更できる。Fromは自己Claimを判定できず、譲渡後も通常の判定権限を持たない。管理者は強制判定可能。
- Verification変更後もObservationが再評価し、所有者・Owned / Formerly Owned・判定権限を同じ結果に合わせる。Negativeにした結果Fromへ戻れば、その時点の既存ルールで判定権限を決める。Acceptの再送をVerificationの再変更として扱わない。

## 状態・データ

`claim_transfers`はClaimに1対1で、from_user_id、to_user_id、pending / accepted / declined / cancelled、created_at、resolved_atを保存する。`claim_transfer_acceptance`は同じClaimに紐づく専用Evidenceテーブルで、accepted_by_user_id、accepted_at、current_owner_user_idを保存する。既存の写真Evidenceやmarketplace/acquisition_dateのCHECK制約を変更しない。Claim削除時は関連レコードをCASCADEで削除する。

申請・応答処理はBEGIN IMMEDIATEを用いる。AcceptのEvidence保存、Claim更新、user_guitars来歴登録、Observation評価・Snapshot反映、結果通知を同一トランザクションで実行する。競合する申請が同時に承認されても、後続処理がCurrent Ownerの変化を検知して拒否する。

Observationは、Claimがactive / Positive、作成者と移転先が有効、accepted状態、Evidenceの承認者がTo、EvidenceのCurrent OwnerがFrom、Claimの作成者がFrom、承認日時がClaim移転日時と一致、評価時点の所有者がFrom、という条件を確認する。管理者がEvidence未取得のClaimをPositiveにしても移転しない。

同日は既存のClaim ID順で評価する。古いIDの申請を後から承認し、既存Claimとの順序によりToへ移転できない場合は、承認トランザクション全体を取り消して競合エラーを返す。承認Evidenceだけ保存して移転しなかった状態を作らない。

Fromの既存user_guitarsに終了日を、Toに取得日と来歴を記録し、Owned / Formerly Ownedの区分はObservation結果から決める。承認待ちのToにはuser_guitarsを作らない。合意後にVerificationで所有者が変わっても、成立した来歴は残る。

申請・承認はBAN / Silent BAN / source / 不存在ユーザーを対象外とする。ToのBANによる再評価も、Transferを作ったFromだけでなくToを参照している個体に適用する。ユーザー削除後の申請は承認不可。EvidenceのユーザーIDは当時の識別記録として保持する。

## API・UI

- `GET /api/transfer-users?viewer_id=…&q=…&offset=…&limit=20`：相手選択専用の検索。公開用ID・Display Name・Account Typeだけを返す。Display Name部分一致とUser ID完全一致。空検索は空結果。自己・無効アカウントは除外。
- `POST /api/individuals/{id}/transfers?viewer_id=…`、body `{to_user_id}`：操作ユーザー自身をFromとして申請。
- `GET /api/transfers/{claim_id}?viewer_id=…`：双方の参加者用の確認画面データ。
- `POST /api/transfers/{claim_id}/resolve?viewer_id=…`、body `{action: accept|decline|cancel}`：本人の役割で操作を制限。同じ応答の再送は冪等で、Evidence・通知を重複作成しない。

Product DetailのOwnership追加でTransferを選ぶとTo検索を表示し、手入力日付・関係者自由文・Memoは表示しない。候補から明示的に選択して申請する。一般のユーザー探索画面は追加しない。

通知クリック、またはUnverifiedタグを開いたClaimのReview TransferからAccept / Decline / Cancel画面へ移動する。Positiveカード、Unverifiedタグ、Negative点の既存Chronicle表示規則を維持する。カード・ポップアップ・Browser ConsoleでFrom / To、合意状態とEvidenceの3項目を確認できる。管理者のVerification UIは既存のものを使用する。

通常のClaim編集APIから相手・移転日を変更することは禁止する。未成立のTransferの通常無効化は拒否し、Cancelへ誘導する。既存のClaim無効化・管理者削除は、合意応答とは別の既存処理として扱う。

## 旧データ・認証境界

旧Transferは所有終了を示す記録で、従来のUnknownへの効果を保持する。既存DBのClaimを新方式へ推測変換しない。新たな旧形式Transferの作成は従来API / Repository入口で拒否し、相手指定方式へ誘導する。Release / Inheritは従来の挙動を維持する。追加テーブルは起動時init_dbで作成し、手動移行は不要。

操作ユーザーはPrototypeIdentityで解決するローカル試作。Acceptは相手アカウントの合意操作であり、画像認証やIdentity Platformによる本認証ではない。GCP移行時は検証済みprincipalからFrom・To操作主体を解決し、ブラウザ指定IDを本人確認として使わない。

## 検証

`test_transfer_claim.py`で承認前後の所有状態、From / To / 第三者の操作、Evidenceの3項目、自己Claim判定禁止、移転後ToのVerification、Negativeと合意の独立、Accept再送時のEvidence・通知・Verification保持、次のTransfer、Decline / Cancel、同時承認、無効ユーザー、候補検索、プロフィールと旧DBを確認する。

旧TransferがUnknownを返す読取テストを追加し、旧APIでTransferを新規生成していたテストはRelease / Inheritの検証に限定した。所有者・判定権限・自己Claimの既存回帰テストも実行する。実ブラウザでは隔離DBでFromの検索・申請→Toへの通知→Accept→所有移転→ToのNegative→合意Evidence保持の往復を確認する。検証結果：Python全体201件通過、2件スキップ（画像認証の追加依存関係がないため）。既存プロフィール更新5件、Console User Detail・共通Product DetailのJS検証が通過。隔離DBのChromiumで検索・From申請・To通知・Accept・Owned移転・ToのNegative・合意Evidence保持を確認し、JavaScript例外は0件。
