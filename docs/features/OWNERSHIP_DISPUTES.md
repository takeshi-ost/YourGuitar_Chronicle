# Ownership Disputes

ローカル試作のAcquire所有権係争。画像審議とは別に、当事者の主張と非公開資料を管理者が確認する。公開サーバーの本人認証・管理者認証を実装したものではない。

## 対象と開始

画像審議を通過してClaimが作成されたユーザーAcquireのうち、PositiveならCurrent Ownerを置き換えるものだけを対象とする。判定は既存のObservation評価器で確認する。Former Owner登録、承認してもFormerly Ownedになる過去Acquire、Listing、Automation、Transferは対象外。

現OwnerのDeclineには理由を必須とし、Negativeと理由を同じトランザクションで保存して申請者へ通知する。申請者はTop Page／User Page最上部のOwnership Disputesから、理由を確認してAccept decisionかAppealを選ぶ。Accept decisionは係争入口を閉じる。無回答はClaim作成から既定14日後に運営への確認依頼を可能にする。`YGC_DISPUTE_WAIT_DAYS`で待機日数を変更できる。無回答による自動移転はしない。

異議申立てには取得経緯を含む説明、相手に示す要旨、追加添付を必須とする。作成済みの競合Acquireからの追加申立ては同じ個体のopen案件に集約する。係争中に新たな所有権Claimを作成することはできない。

## 保存と閲覧

- `ownership_disputes`: 個体、原Owner、係争中に維持するOwner、状態、version、決定・理由。
- `ownership_dispute_claims`: 案件、対象Acquire、申請者。Claim作成者は変更しない。
- `ownership_declines`: 現Ownerの理由と、申請者が納得した日時。
- `ownership_dispute_evidence`: 対象Acquireに紐づく特殊Evidence。提出者、説明、添付原本、提出要旨、管理者が公開した要旨、日時を保存する。
- `ownership_dispute_events`: 開始、追加提出、要旨公開、資料要求、決定、再審議の履歴。

原本・説明・未公開要旨は提出者と管理者のみ閲覧できる。他方には管理者が確認して公開した要旨のみ返す。複数の申請者がいても他の申請者のEvidenceは閲覧できず、原Ownerは各自に対する要旨を閲覧する。APIも同じ制限を検査し、添付取得はprivate/no-storeとする。公開media/galleryには追加しない。

添付は1提出につき静止画像またはPDFを1件、最大12 MB。画像は既存の審議画像処理でEXIF除去・JPEG化する。PDFはダウンロードとして配信する。1案件100提出、添付合計256 MBを上限とする。複数資料は1件のPDFなどにまとめる。提出・公開済み要旨の上書きは行わず、訂正は次のラウンドの提出として残す。

## 証拠提出ラウンド

各ラウンドでは、対象Acquireごとに申請者と原Ownerがそれぞれ1回だけ提出できる。異議申立て時の証拠を第1ラウンドの申請者提出として扱う。画面は提出者名とSubmittedを表示し、全員の提出が揃うとUnder reviewへ進む。提出済みの側には提出フォームを表示せず、APIでも再提出を拒否する。

管理者は証拠の提出状況にかかわらず、未提出・片側提出・審査中のどの段階でも理由付きで裁定できる。Under reviewは「双方提出済み・結果待ち」を表す状態であり、裁定の前提条件ではない。双方の提出が揃った後は、理由付きのRequest additional evidenceも選べる。追加要求は次のラウンドを作成し、双方が再度1回ずつ提出できる。説明・要旨は必須、追加ラウンドの添付は任意。未提出者がいる段階では次ラウンドの追加要求はできないが、裁定は可能。複数のAcquireを含む案件は、Acquireごとに双方の提出を揃える。審査中の案件への追加申立ては次の提出ラウンドまで待つ。

ラウンドと提出状態は`ownership_dispute_rounds`、`ownership_dispute_round_parties`、Evidenceとの対応は`ownership_dispute_round_evidence`に保存する。古い画面から前ラウンドの提出を送信した場合も拒否する。既存案件のEvidenceは削除せず、第1ラウンドに移行し、既にEvidenceがある側を提出済みとする。再審議も新しいラウンドから始める。

## 係争中のロック

Current Ownerを維持し、当事者と管理者にのみUnder disputeを表示する。通常の来歴閲覧・所有に影響しない投稿は継続できる。

所有関係のClaim（Ownership / Listing / Identity Correction）の追加・変更・削除、Transfer承認、競合Acquireの作成をDBトリガーで停止する。個体のCurrent Owner変更も拒否し、管理画面からの通常Verification変更では迂回できない。一般の未回答リストから停止中の操作を除く。当事者のProduct DetailにはUnder disputeと詳細への導線を表示し、Ownership・Former Ownerのメニューを無効化する。新しいAcquire申請は未保存フォームの発行段階でも停止する。Specification/Repair・Incident・Event・Mediaの通常投稿は維持する。

審議ワーカーは係争中個体の未処理Acquireを確保せず、解決後の実行で再開できる。すでに確保済みの審議結果も、係争中はClaim作成を拒否する。この場合は既存のlease失効・再試行の扱いに従う。

## 管理者操作

Browser ConsoleのOwnership Disputesは係争中を初期表示し、Resolved／All casesへ切り替えられる。一覧に個体・原Owner・申請者・開始日時・最終更新・状態・表示件数を表示し、詳細で双方の原本を確認する。詳細モーダルで要旨の確認・公開、理由付き追加資料要求、原Owner支持、申請者支持を行う。複数のAcquireがある場合は支持する申請者のClaimを選択する。

- 原Owner支持: 対象AcquireをすべてNegativeにする。
- 申請者支持: 選択したAcquireをPositive、他の対象AcquireをNegativeにする。
- 既存の管理者Verification処理で記録し、Observation・Owned/Formerly Ownedを再評価する。結果のCurrent Ownerが選択したユーザーと一致しなければ全体をロールバックする。
- 決定、理由、監査記録、通知は同じ書込みトランザクションで反映する。画面のversionが古ければ拒否する。
- 解決後は個体の新しい所有操作を再開する。係争対象Claimだけは通常の判定変更・編集・無効化・削除を引き続き禁止する。

Reopen for reconsiderationは理由付きで管理者が実行する。現在のOwnerが直前決定のOwnerのままで、別の係争が開かれていない場合に限る。原Ownerと元の申請者・Evidenceを保持し、再審議中はその時点のOwnerを維持する。後のTransfer等で別のOwnerに移った古い係争は再開せず、新しいAcquireが必要。

## 保留事項

- 係争開始後の第三者の新規申請を、Claimを作らず案件へ参加させる受付。
- 追加資料への回答期限、長期保留の終了・自動督促。
- 将来のCurrent Ownerが終了済み係争跡をChronicleで目立たなくする表示機能。Verificationとは分離し、履歴・Evidenceは消さない。
- 本番環境の認証、PostgreSQL向けの同等ロック、永続ファイル保存。

## 検証

`test_disputes.py`でラウンドごとの一回提出・古いラウンドの拒否・既存Evidenceの移行・証拠未提出時の管理者裁定・ラウンド別履歴、理由必須、時系列による対象限定、双方の決定と所有権・判定権限、再審議、Evidenceの閲覧制限、同時申立て、古い管理画面の拒否、再起動後のロック、係争中Transfer・審議結果の停止を確認する。実ブラウザーでは一時DBで申立て、画像提出、要旨公開、管理者判断を確認する。

ユーザーへの未決着の係争案内は、Top Pageと本人User Profileの重要情報領域に表示する。係争中案件と、Decline済み／無回答期限を過ぎた異議申立て候補がなければ隠す。User Profile欄の専用ボタンは置かない。Product DetailのUnder disputeは所有申請案内と同じowner-claim-cardを使い、同じ幅・配置・共通枠で係争詳細を開く。

### Dispute Detailsの表示

上部にAcquire ID・申請者・現在のOwner・申請日時・係争ステータスを表示する。日時は閲覧端末のローカル時刻。区切り線の下にRound 1から順に、提出・審査開始・要旨公開などの時系列記録と、末尾のReview resultを表示する。継続時は次のラウンドを続ける。

提出者と管理者には提出サマリーを直ちに記録内へ表示する。他方への公開は引き続き管理者が確認した要旨のみ。説明・添付操作は展開式とし、提出可能な当事者だけに最新ラウンド直下のフォームを表示する。提出成功時は記録を更新してフォームを取り除く。

Round内では開始・追加要求の重複する履歴行を省略し、提出者は役割ラベルではなくユーザー名で表示する。証拠待ちの間はReview result行を表示せず、提出先Acquireが1件ならフォームの選択欄を省く。追加要求の理由は前ラウンドのReview resultに残す。
