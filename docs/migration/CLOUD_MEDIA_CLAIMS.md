# Cloud Media Claim 投稿・編集

2026-10-07。PR55の認証済みClaim投稿に、本人のMedia Claimを追加する移植単位。公開・配置は別承認。既存の管理用Media機能、公開カタログ、所有審議用の写真の公開範囲は変更しない。

## 投稿と編集

- 公開Product DetailのAdd Claimから個体を選択し、既存のログイン・メール確認・戻る／進むの導線を使う。選択・ログインだけでは投稿しない。
- メール確認済みの有効な投稿者が、1つのMedia Claimへ新規写真1〜10枚、任意キャプション（2000文字以内）、発生日をまとめて提出する。日時は既存のタイムゾーン・未来日付禁止に従う。
- クラウド画像の安全な入力制限に合わせ、JPEG / PNG / WebPの静止画像、1枚8 MiB以内・800万画素以内、写真合計24 MiB以内。ローカル試作のGIF／12 MB制限とは別。EXIF方向を補正し、メタデータを除去、透明部分を白背景にして最長辺2048 pxのJPEGへ正規化する。ファイル名は保存しない。
- 自分の一覧から日付とキャプションを編集できる。添付写真は既存ローカル編集と同じく不変。写真の差し替え・追加・取り外しは提供しない。訂正写真が必要なら、新しいClaimを作り、必要に応じて元のClaimをDeactivateする。
- DeactivateはClaimのinactive化のみ。画像オブジェクト、Evidence、過去バックアップの参照を消さない。Inactiveも本人の管理一覧で確認・閲覧できる。復活・物理削除・自動回収は今回の対象外。
- Current Ownerの作成はPositive、他人の作成はUnverified。共有RepositoryとObservationの規則を利用する。Media投稿で所有者・所在地を変更しない。
- 編集後もVerificationを維持する。写真を不変としたまま日付・キャプションを編集する既存仕様であり、暗黙の再承認ルール変更は行わない。作成・更新日時と判定状態を表示する。

## 写真の閲覧範囲

この移植単位の写真は公開しない。Positiveであっても公開カタログは従来どおり写真、本文、投稿者、Evidence、Storage参照を返さない。

認証済みの本人は自身のactive / inactive Mediaを閲覧できる。その時点のCurrent Ownerは、通常Owner Verificationの対象になっているactiveな他人のMediaだけを判定画面で閲覧できる。自己判定は禁止。所有者が移った場合は前Ownerの新規取得要求を拒否し、新Ownerに現在の通常判定権限を適用する。BANされた投稿者の画像をOwnerへ新たに配信しない。Adminであるだけで通常入口の他人の写真閲覧・編集権限は付かず、既存の明示的なAdmin画像入口はそのまま別経路とする。

写真はギターID、Claim ID、media_assets IDの組合せから取得する。Claim自身がMediaであり、写真の個体・投稿者がClaimと一致し、別ClaimのEvidenceとして共有されていないことを確認する。Listing／Acquire写真、所有審議のcloseup・overview・reference、任意Storage参照を入力または閲覧対象に指定するAPIはない。新しい投稿写真だけを新しいオブジェクトへ保存する。

ブラウザはBearer付き取得からBlob URLを作る。閉じる・個体変更・アカウント変更・SignOutでは画像を破棄する。遅れて返る画像を別の画面・アカウントへ差し込まない。Owner画面は写真を自動一括取得せず、View photosで選んだ1つのClaimだけを読み込む。別Claimを開くと以前の要求・画像・判定確認を破棄する。Owner判定は添付を読み込めた状態から進め、画像失敗や改訂競合がある場合は最新内容の再取得が必要。既に正当に取得した画像の保存や画面撮影を取り消す仕組みではない。

## APIと保存

- `POST /api/auth/guitars/{individual}/media-claims`：multipart/form-data。`metadata`は1つだけのJSON文字列で、`claim_type: "media"`、`body`、`occurred_at`のみ。`images`は1〜10個のファイル。未知の項目、重複metadata／JSONキー、Storage参照、ユーザー・Verification指定を拒否する。
- `GET /api/auth/guitars/{individual}/claims`：既存の自分の一覧にMediaを含む。Mediaだけに`media_items: [{id, mime_type: "image/jpeg"}]`を追加する。Storageキー・世代・元ファイル名は返さない。
- `PATCH /api/auth/guitars/{individual}/claims/{claim}`：`claim_type: "media"`、`body`、`occurred_at`、現在の`revision`のみで編集。
- `POST /api/auth/guitars/{individual}/claims/{claim}/deactivate`：既存のrevision付き無効化。
- `GET /api/auth/guitars/{individual}/claims/{claim}/media/{asset}?revision={revision}`：現在のClaim改訂に束縛したJPEG配信。古い改訂は409、権限・組合せ不一致は404。署名URL・公開ACL・任意オブジェクト取得は作らない。
- 既存Owner responsesへMediaの添付IDを追加し、同じ内容結合revisionを利用する。

IDは正のBIGINTで、JSONでは十進文字列。私的な応答は`private, no-store`、`Vary: Authorization`、`nosniff`。写真はさらにsame-origin Resource Policyを使う。Cookie認証は使わず、cross-site書込、圧縮本文、不要クエリを拒否する。multipartは入力総量・各画像・フィールド数・ヘッダー長を制限し、途中切断・不完全な終端を拒否し、キャンセル後も保護された後処理で一時ファイルを閉じる。正規化からコミットまでの処理は1プロセス2件までに制限し、混雑時はStorage書込前に409を返す。永続的な利用上限や分散レート制限ではない。未知の内部エラーでSQLや保存参照を返さない。

既存のAccounts正本・投影一致・関係者・Operationsモードのロック、保守／Crawl排他を維持。共有Claim作成処理をPostgreSQLの制限付きruntime roleへ接続し、Claim、画像参照、Evidence、通知、Observation再評価を同じChronicleトランザクションで確定する。スキーマ・権限変更、SQLiteへの代替、オンライン初期化はない。

画像オブジェクトはcontentスコープのサーバー生成キーと固定generation参照を使う。DB保存前の失敗が確定した場合にだけ、この試行で保存成功を確認した新規画像を補償削除する。既存画像や不明な世代には触れない。コミット結果が不明な場合は画像を保持する。再送は自動で行わず、下書きを保持し、自分の最新一覧を確認してから明示的な再試行を選ぶ。ネットワーク越しのExactly-once作成や孤立オブジェクト自動回収は今回追加しない。

revisionには従来のClaim状態・内容・投稿者・日時に加え、添付Evidenceの順序・IDと画像参照・世代・属性を含む。日付・キャプションの同一時刻編集や管理経路での添付変更後も古い確認を拒否する。参照をハッシュの外へ公開しない。従来ローカルパスの画像を自動変換せず、配信できない写真はエラーにし、パスの露出や無断コピーをしない。

## Service Modeと検証

Normalは認証済み本人の読取・書込、Read Onlyは写真を含む認可済み読取のみ。Admin Onlyは正本Adminのみ、OfflineはAdminを含む一般入口を停止。既存Adminの保守用経路とは区別する。

使い捨てSQLite／モックStorageのサービス・HTTP試験、NodeのUI試験、使い捨てPostgreSQL／Chromiumスイートを統一runnerへ登録。実写真・実認証・実ステージングのデータには触れない。クラウド作業環境で禁止されたPostgreSQL／Chromium起動は試さず、Macまたは通常CIの同一checkpointで後続確認する。詳細と実行結果は[今回の引き継ぎ](../history/CLOUD_MEDIA_CLAIMS_HANDOFF_2026-10-07.md)。

公開写真の同意・公開範囲・公開ギャラリーへの接続は未決定のまま。Event、Transfer／Release、Listing訂正は別の移植単位。
