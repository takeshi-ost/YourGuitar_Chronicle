# Cloud Identity Correction

2026-10-07。PR58統合済みmainを基点とする、本人のListingから独立した訂正Claimを作るcheckpoint。公開・配置、実データの変更は別承認。

## 訂正の意味と入口

- 認証済みアカウント画面に、自分が作成した有効なListingの一覧を設ける。現在所有しているかどうかは入口の条件にしない。他人のListingは、Current OwnerやAdminであってもこの本人用入口から扱えない。
- ListingのEditを選ぶと、元のListingは書き換えず、別のIdentity Correctionを作ることを説明する。確認後、現在のMaker / Model / Year / Serialと訂正理由を入力する。
- MakerとSerialは必須。ModelとYearは空欄へ訂正できる。Finish、所有者、所在地、写真、Evidence、元Listingの日付はこのフォームで変更しない。
- 変更前は元Listingの入力値ではなく、その時点のIndividualの現在値。変更した項目の旧値・新値を表示し、確認したrevisionで明示的に提出する。無変更の提出は拒否する。
- 既存Repositoryの意味を維持し、本人の訂正はPositiveで作られ、Observationを同じトランザクションで再評価する。発生日は対象Listingの発生日、なければ作成日時を継承する。通常Owner Verificationの対象にはしない。管理者の別経路の判定は維持する。
- 訂正は既存の時系列評価に従う。過去のCorrectionを推測して作り直したり、一括再承認したりしない。元Listing、過去の訂正、画像・Evidenceを上書きしない。

## 重複と競合

新しいMakerとSerialを既存規則で正規化し、別Individualに同じ組があれば拒否する。Modelが違っていても拒否する。大文字小文字や既存の正規化規則を無視した別表記で回避できない。同一個体は除外し、同じMaker / SerialのままModelやYearだけ訂正できる。

これは訂正処理に限った検査。全体の3項目unique制約、他経路で記録された重複、Repeated一覧、後の人によるMerge / Delete方針は変更しない。自動Mergeやデータ移行はしない。エラーには競合相手のIndividual IDや非公開情報を含めない。

訂正の検査・Claimと変更項目の保存・Snapshot再評価は同一トランザクションで行う。入力した組に加え、後の日付の訂正が一部の項目を上書きした後の最終identityも検査する。SQLiteの直接呼出しにも書込トランザクションを用い、CloudはAccounts正本・投影・関係者・Operationsモードと既存のcontent／保守・Crawl排他を使う。同時訂正や既存のCloud登録経路との競合で、検査の直後に別個体が同じ組を得ることを防ぐ。

revisionはListing、現在identity、関連する訂正履歴などのサーバー上の状態に結び付ける。表示後の訂正・対象変更・無効化は古い確認を拒否する。結果が不明なPOSTを自動再送しない。画面で最新の本人履歴を読み、結果を確認して明示的に再確認する。閉じる、戻る／進む、SignOutで未提出の確認を失効させる。閉じることは、実行済みサーバー処理の取消ではない。

## 認可・公開境界

作者はBearerで確認した有効・メール確認済みのAccounts正本から決める。クライアントのuser ID、role、Verification指定は受け付けない。BAN・disabled・投影不整合、Read Onlyの書込、一般ユーザーのOffline／Admin Onlyアクセスを既存のフェンスで拒否する。通常Ownerとしての権限を新しく付与しない。係争の既存書込制限も維持する。

訂正理由、旧値・新値の完全な履歴は本人用APIだけで返す。公開カタログの固定フィールド制限は変更しない。認可された訂正の結果としてMaker / Model / Year / Serialの現在値と検索結果が変わることはある。元Listingの公開固定項目は元の記録のまま。本文、作者、所在地、Evidence、写真、Storage参照を追加公開しない。

## API

- `GET /api/auth/identity-corrections`：本人の有効なListing一覧。`after` / `limit`のID cursorでページ送り。
- `GET /api/auth/identity-corrections/{listing}`：対象Listing、現在identity、本人の訂正履歴、現在revision、書込可否。履歴も`after` / `limit`で制限する。
- `POST /api/auth/identity-corrections/{listing}`：`revision`、`manufacturer`、`model`、`year`、`serial_number`、`reason`のJSONだけを受け付ける。

GETの既定件数は25、最大50。IDは正のBIGINTを十進文字列で返す。未知・重複JSONキー、余分なquery、重複認証ヘッダー、圧縮本文、cross-site書込、過大入力を拒否する。レスポンスはprivate / no-store。SQL、内部例外、保存先を返さない。新しいschema、runtime権限、認証設定、Storage APIは不要。

Maker / Model / Serialは各200文字、Yearは40文字、理由は2000文字以内。保存済みの旧記録にも応答上限と形の検査を適用し、過大・不正なidentityや変更履歴があれば入口を利用不可として扱う。確認する旧値を切り詰めたり、履歴を黙って変換したりしない。そうした旧記録の個別修復は別作業。

## 検証・引き継ぎ

合成SQLite／HTTP、Node UI、合成PostgreSQLと実Chromiumの受入を追加する。Model違いのMaker / Serial重複、正規化、同時競合、作者／Ownerの分離、BAN・disabled・Service Mode、stale revision、結果不明・繰返し・画面中断、公開境界と元記録の維持を確認する。

このCloudでは、既に拒否されたPostgreSQL導入やChromium起動を再試行しない。Macまたは通常CIで、同一checkpointの実PostgreSQLとChromiumを含む総合検証を公開前ゲートとする。[適用・検証の引き継ぎ](../history/CLOUD_IDENTITY_CORRECTION_HANDOFF_2026-10-07.md)に最終結果を記す。
