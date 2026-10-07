# ユーザー向け操作ガイド

対象：現在のローカル版を利用する人。英語ラベルを目印に操作を説明する。ヘッダーの言語選択で日本語へ切り替えられる。管理用Consoleの操作は[運用ガイド](../operations/README.md)を参照。

## ギターを探す・履歴を見る

1. Top PageのAll Discovered Guitarsで検索・並べ替えを行う。
2. ギターの行を選び、Product DetailのSpecification、Chronicle、画像を確認する。行選択後は上下キーでも移動できる。
3. 投稿者・Ownerの名前をクリックするとUser Profileを開く。♡／♥でお気に入りを登録・解除できる（ログイン時）。

デスクトップの一覧とDetailは個別にスクロールできる。狭い画面ではDetailを開閉して閲覧する。New Discoveryには新着個体とFollow先の活動が表示される。

## ローカルでサインインする

GuestのSign Inを開き、フォーム最下部で既存ユーザーを選ぶ。入力メール・パスワードでは本人認証せず、選んだユーザーでサインインする。ヘッダーのSignOutでログアウトする。

Create AccountではDisplay Name、User / Shop、Terms／Privacyへの同意を入力し、ローカルアカウントを作成してサインインする。Profileと同意は保存されるが、メール・パスワードは送信・保存せず、Googleの認証アカウントも作成しない。

## プロフィールを整える・交流する

本人のSettingsでDisplay Name、User / Shop、居住地、自己紹介、画像、Signature Guitar、Themeなどを設定し、Saveで保存する。公開範囲を選べる項目もある。言語はヘッダーで選ぶ。

他ユーザーのProfileでFollow / Unfollowやメッセージ開始を行う。ヘッダーのMessagesで会話、Notificationsで通知を確認する。未読があるボタンは強調表示される。Owned / Formerly Ownedは所有履歴から分類され、手動で一覧に加える操作ではない。

## 未登録のギターを追加する

本人ProfileのOwned Guitars直下からAdd Guitarを開き、仕様などの必要事項を入力する。Generate Challengeで撮影用文字列を発行し、期限内に指定写真を選んでSubmitする。Listing審議が通過すると個体が登録される。同じメーカー・シリアルの個体がある場合は、既存個体へのAcquireへ案内される。

## 所有を申請する・Claimを追加する

Ownerが不明・非ユーザーの個体はProduct Detailの所有申請案内からAcquireを開く。他ユーザー所有の個体はChronicleのClaim追加からOwnershipを選び、警告を確認して申請する。写真審議の通過後、現Ownerがユーザーの場合はOwnerの承認を待つ。画像審議の通過だけで所有者が変わるわけではない。

その他の仕様・修理・出来事・画像などはChronicleのClaim追加から種別を選ぶ。Current Ownerは対象となる他ユーザーのClaimを判定できるが、自分のClaimは判定できない。

## 申請の確認・譲渡・係争

未決着の申請や回答が必要な所有操作はTop Page／本人Profileの重要情報領域に表示される。Detailから内容を確認する。他ユーザーのProfileにはこの領域を表示しない。

TransferはCurrent Ownerが相手を指定して申請し、相手がAccept / Declineで回答する。Acquireの却下や長期無回答に異議がある場合は係争の導線から説明・相手への主張を提出する。非公開説明と、管理者確認後に相手へ示すメッセージを区別する。係争中は対象の所有変更が制限される。

## モーダルを閉じる・メンテナンス中の表示

モーダルはCloseなどのボタン、Escape、外側クリックで閉じる。未保存入力は失われる場合がある。閉じても提出済み申請や開始済みサーバー処理は取り消されない。RequestのKeep Requestは入力だけを保存し、写真は次回選び直す。取消はCansel Requestを使う。

メンテナンス時の重要情報領域はサービス案内のみを表示する。Read-onlyでは更新できず、Offlineでは一般利用を停止する。

詳細な条件は[Claim](../features/CLAIMS.md)、[申請](../features/OWNERSHIP_REQUESTS.md)、[Transfer](../features/TRANSFER_CLAIM.md)、[係争](../features/OWNERSHIP_DISPUTES.md)を参照。

## クラウド版：自分のListingを訂正する

この項目はクラウド版の追加checkpointに対応する。公開環境への配置は別途行う。

1. メール確認済みの自分のアカウントで、本人のListing一覧を開く。所有者が変わっていても、自分が作成した有効なListingが対象になる。
2. 対象のEditを選び、元Listingを残して別のIdentity Correctionを作る説明を確認する。
3. 現在のMaker / Model / Year / Serialを訂正し、必要なら理由を入力する。
4. 変更前と変更後を確認し、明示的に提出する。訂正は通常Ownerの承認待ちにはならない。
5. 本人用の履歴で結果を確認する。競合や結果不明の表示が出た場合は、最新の履歴を読み直し、反映済みでないか確認してから操作する。

同じメーカー・シリアルの別個体がある場合は訂正できない。ここで個体を自動統合しない。写真、所有者、所在地はこの操作では変更しない。
