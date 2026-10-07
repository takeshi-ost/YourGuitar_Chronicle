# Cloud Event Claim 投稿・編集とOwner審議

2026-10-07。PR57統合済みmainを基点に、認証済みClaim投稿へEventを追加する単位。公開・配置は別承認。Identity Correction、公開写真の同意・ギャラリー、所有審議の実データ受入は含めない。

## 投稿・編集の意味

- 公開Product DetailのAdd Claimから対象を引き継ぎ、メール確認済みの有効な本人がEventを投稿する。選択・ログインだけでは投稿しない。
- 種類はExhibition / Performance / Recording / Auction / Other。本文は空白のみを除き必須、2000文字以内。発生日も必須で、既存のタイムゾーンと未来日付禁止に従う。
- 写真は任意の0〜10枚。テキストだけのEventにStorageを要求しない。写真は[Cloud Media](CLOUD_MEDIA_CLAIMS.md)と同じJPEG / PNG / WebP静止画、1枚8 MiB・800万画素、合計24 MiB以内。EXIF方向を補正し、メタデータと元ファイル名を残さず、最長辺2048 pxのJPEGへ正規化する。
- Current Ownerの作成はPositive、第三者はUnverified。共有Repository・Observationを再利用し、Eventの投稿・判定で個体のidentity・Owner・Locationを変えない。
- 自分の一覧で日付・本文を編集する。種類と写真は不変。従来の編集と同じくVerificationを維持し、暗黙の再承認ルールを追加しない。修正写真には新しいClaimを使う。
- Deactivateはinactive化のみ。画像・Evidence・バックアップ参照は削除しない。本人はinactiveも一覧・写真で確認できる。復活・ハード削除・自動回収は追加しない。

## 私的な写真と完全なOwner確認

写真の読取対象は認証済みの作成者、通常Owner Verificationの対象となるその時点のCurrent Owner、既存の別経路のAdmin。Adminであるだけで一般の本人編集・Owner写真入口の権限は得られない。自己Claimの通常判定、元Ownerの判定、BANされた作者の写真の新規Owner配信は禁止する。

EventのOwner一覧には既存の種類・日付・全文に加え、添付IDをすべて返す。写真がないEventは明示的に空配列で表す。写真があるEventの判定は全添付を読み込めてから有効にし、欠落・失敗した写真や不正な添付投影を「写真なし」とみなさない。1つのClaimを選択して写真を取得し、別Claim・閉じる・別個体・SignOutではBlobと古い確認を破棄する。既に正当に取得した画像の保存や画面撮影を取り消す機能ではない。

添付は個体ID・Claim ID・画像IDから特定し、作者・個体・画像形式・Evidenceの専属性を再検査する。Listing / Acquireの審議写真、別Claimの写真、任意Storage参照をこの入口へ渡せない。配信は固定generationのJPEGをBearer付きで取得する。署名URLや公開ACLは作らない。

Owner確認revisionはClaimの本文・種類・日付・状態・作者・日時と、添付Evidenceの順序・ID、画像参照・世代・属性をハッシュに含める。テキストのみから写真が追加された場合、写真が削除された場合、同一時刻の本文変更も古い確認を拒否する。Owner移転・BAN・無効化も現在の権限を再確認して拒否する。

旧ローカルパス写真をコピー・変換しない。作者はそのClaimの本文編集と無効化ができるが、写真の配信は不可。Owner画面も写真を見ない判定を案内せず、通常Owner応答APIはクラウドで有効な添付参照を持たない写真付きEvent / Mediaの判定を拒否する。実際の画像取得失敗もUIの判定を停止する。新たなVerification方針や判定済みClaimの一括変更はない。

公開カタログの投影は変更しない。EventがPositiveでも本文・写真・作者・Evidence・Storage参照を一般公開しない。

## APIと保存

- `POST /api/auth/guitars/{individual}/claims`：写真なしEventをJSONの`claim_type: "event"`、`event_kind`、`body`、`occurred_at`で投稿。
- `POST /api/auth/guitars/{individual}/event-claims`：multipartの`metadata`に同じJSON、任意の`images`0〜10個。1つのmetadata以外、未知のキー・重複JSONキー・ユーザー指定・判定状態・Storage参照を拒否する。
- `GET /api/auth/guitars/{individual}/claims`：自分のEvent履歴に`event_kind`と`media_items`を返す。写真なしEventは`media_items: []`。
- `PATCH /api/auth/guitars/{individual}/claims/{claim}`：同じEvent入力と現在の`revision`。種類変更を拒否し、写真は変更しない。
- `POST /api/auth/guitars/{individual}/claims/{claim}/deactivate`：現在の`revision`のみ。
- `GET /api/auth/guitars/{individual}/claims/{claim}/media/{asset}?revision=...`：既存のMedia写真配信入口をEventにも適用。
- 既存のOwner responsesで写真なし／写真付きのEventを完全に確認する。

IDは正のBIGINTを十進文字列で返す。本文、画像、multipartの総量・ヘッダー・フィールド数を制限し、中断時のspoolも閉じる。Event metadataは2000文字のUnicodeをJSON escapeした場合も収まる32 KiB上限。認証済みの操作主体をAccounts正本から決め、Cookie・クライアント指定の作者やroleは使わない。cross-site書込、圧縮本文、余計なquery、不正なタイムゾーンは拒否する。内部エラーのSQLや保存先を返さない。

既存のAccounts正本・Chronicle投影・関係者・Operationsモードと保守／Crawl排他のフェンスを使う。スキーマ・runtime権限・認証設定・初期化処理を変更しない。Normalで認可済み読取／書込、Read Onlyは読取のみ、Offlineは一般入口を停止、Admin Onlyは正本Adminだけが通れる。モードを通っても作者／Current Owner条件は必要。

写真正規化からcommitまでの同時処理枠はMediaと共有する。Claim・画像参照・Evidence・通知・Observationを同一Chronicleトランザクションで確定する。確定前の失敗ではこの試行の既知の新規オブジェクトだけ補償削除し、commit結果不明では画像を保持する。画面は自動再送せず、最新の自分の一覧を確認してから明示的に再試行する。exactly-once保証や孤立画像の自動回収は追加しない。

## 検証と引き継ぎ

使い捨てSQLite／モックStorage・HTTP、Node UI、合成PostgreSQL・Chromiumの受入を追加する。実画像、実アカウント、実DB、実ステージングへの操作は不要。実PostgreSQL／ChromiumはこのCloudで未実行であり、過去に拒否されたインストール／起動を再試行しない。同じ最終checkpointのMacまたは通常CIでの受入を公開前ゲートとする。検証結果と適用手順は[引き継ぎ](../history/CLOUD_EVENT_CLAIMS_HANDOFF_2026-10-07.md)。
