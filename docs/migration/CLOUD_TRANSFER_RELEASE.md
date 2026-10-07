# Cloud Transfer / Release

2026-10-07。認証済みWebへの所有ワークフローの移植単位。LOCALの`TRANSFER_CLAIM.md`、Claim中心のObservation、Owner Verificationの不変条件を共有する。公開・PR・統合・配置は別承認。

## 提供する操作

- Accountの所有ギター、公開Product DetailのOwnership導線から、サインイン後に対象個体の所有画面を開く。画面を開く、認証する、相手を選択するだけでは所有関係を変更しない。
- 本人に関係するTransferの一覧と詳細、本人が作成したReleaseの履歴を確認する。相手からの未回答Transferは本人Accountの一覧から受領・辞退できる。宛先のメールアドレス取得・メール通知は追加しない。
- Current Owner本人だけがTransferを申請し、検索結果から移転先を明示的に選ぶ。Fromは検証済みprincipalから決まり、ブラウザ指定の作成者・ロール・判定状態は受け付けない。
- Transferは`ownership_source='user_transfer'`、Unverified、日付なしで開始する。成立前にToをOwnedへ追加しない。Transfer専用の入力には写真・自由文・手入力の移転日を要求しない。
- To本人だけがAccept / Decline、From本人だけが未成立のCancelを行う。各操作は対象・相手・結果を確認してから送信する。
- AcceptはFromが今もCurrent Ownerで、両者が有効な通常アカウントであることを再検査する。承認者ID・承認日時・承認時点のCurrent Owner IDのEvidenceを保存し、承認日時を移転日時にする。Claim、Evidence、来歴、通知、ObservationのSnapshot反映を同一Chronicleトランザクションで行う。
- Current OwnerのReleaseは日付と任意本文を入力する。共有RepositoryのRelease処理でClaimと来歴を残す。現在値は時系列のObservation評価結果で決め、過去日付だからといって後の取得Claimを上書きしない。ReleaseとAutomation専用のOwnership Lost、Incident / Lostは別の意味であり、この画面ではLostを作成しない。

## 維持する所有・判定規則

合意とVerificationを分離する。成立済みTransferを後からNegative / Unverifiedにしても、合意状態と受領Evidenceは残る。Acceptの同じ応答を再送しても、Evidence・通知・来歴を重複させず、管理者が変更したVerificationをPositiveへ戻さない。

Fromは自分のClaimを判定できない。移転後は旧Ownerとして通常判定権限を失う。Toは自身が受領したPositiveなTransferを通常Verificationで変更できない。後のOwnerと管理者には既存の別経路の規則を適用する。既存のprivate MediaのOwner配信も、その時点の判定権限に従う。

A→B→Cの後にA→Bの判定・有効性を変更しても、B→Cが自身の受領Evidence等の条件を満たす限りCを維持する。成立済みTransferを再評価するとき、直前のOwnerがFromであることを再要求しない。受領時の所有者検査と保存Evidenceが根拠である。

同日のClaim ID順により受領後もToが採用されない場合は、受領トランザクション全体を取り消す。古い所有者画面からのTransfer/Release、競合受領、未反映のアカウント変更、所有係争中の変更は拒否し、再読込を求める。係争の開始・証拠提出・管理者裁定UIは今回追加しない。

旧形式Transfer・旧Inherit・Automation Release等の読取互換はそのまま。新しい旧形式TransferやInheritを作らず、既存Claimを推測変換しない。汎用Claim編集APIではTransferの相手・日付・状態を変更できない。通常Releaseの編集・無効化、Transferの一般無効化・物理削除は今回の追加画面に含めない。

## APIとプライバシー

- `GET /api/auth/ownership-transfers?after=&limit=`：本人がFrom/ToのTransferのみ、ID降順のページ取得。
- `GET /api/auth/guitars/{individual}/ownership?after=&limit=`：本人に関係する個体の所有状態、本人のReleaseと参加Transferの履歴、現在のrevision。
- `GET /api/auth/guitars/{individual}/transfer-users?q=&offset=&limit=`：Current Ownerの相手選択専用検索。空検索は空結果。Display Nameの部分一致、User IDの完全一致。自己・source・BAN・Silent BAN・利用不可のアカウントは除外する。一般のユーザー一覧、メール、所在地、プロフィール本文、認証識別子は返さない。
- `POST /api/auth/guitars/{individual}/transfers`：`{to_user_id, revision}`。
- `GET /api/auth/transfers/{claim}`：From/To本人の詳細。通常Admin権限だけでは他人の参加者用入口を開けない。
- `POST /api/auth/transfers/{claim}/resolve`：`{action: accept|decline|cancel, revision}`。
- `POST /api/auth/guitars/{individual}/release`：`{occurred_at, body, revision}`。

個体・Claim・利用者IDは正のBIGINTを十進文字列として扱う。Email確認済みのBearerとAccounts正本から操作主体を解決し、Cookieや`viewer_id`は本人確認に使用しない。未知/重複JSONキー、余計なquery、cross-site書込、圧縮本文、不正な日付とタイムゾーンを拒否する。private応答はno-store、AuthorizationのVary、nosniff。内部例外のSQL・個人情報をエラー本文に出さない。

一般公開カタログのClaim投影は変更しない。Transferの相手、合意Evidence、Release本文、利用者プロフィールをこの移植で公開しない。参加者画面の名前はテキストとして表示し、未提供の公開プロフィールへのリンクを作らない。

## 競合・通信・運用

Ownership revisionはOwnerだけでなく所有関係のClaim・Transfer等を含み、新しい未成立Transferの作成でも変わる。作成とReleaseはそのrevisionを比較して更新する。受領/辞退/取消もレビューしたTransferのrevisionを比較し、役割・現在の所有状態を同じフェンス内で再検査する。同一の終端応答の再送は、既存の冪等応答を返す。

Accounts正本とChronicle投影の一致、関係者、Operationsモード、保守/Crawlの排他を維持する。既存の制限付きPostgreSQL runtime roleだけを使い、スキーマ移行、権限追加、SQLiteへのフォールバック、オンライン初期化はしない。

Normalでは認可済み読取・書込、Read Onlyでは認可済み読取のみ。Offlineは通常Adminを含む一般入口を停止し、Admin Onlyは正本Adminだけが利用できる。モードを通っても参加者・Current Ownerの条件は省略しない。

ネットワーク結果不明は成功/失敗を推測しない。UIは自動再送せず、最新の認可済み状態を確認するまで操作を止める。閉じる・戻る/進む・新しい個体・SignOut後の遅い応答は古い画面を復活させない。成立済みの書込応答は、同じアカウントと対象が継続していればダイアログを閉じた後でもOwned/Formerly Ownedを更新する。

## 検証

使い捨てSQLiteのサービス/HTTP試験、Node UI試験と、実PostgreSQL/Chromium用の合成fixtureスイートを統一runnerに追加する。PG fixtureの初期化・sequence設定・故障注入はDB ownerが行い、サービス操作は制限付きruntime roleで検証する。実DB、実受領、メール、認証、写真、Service Mode、Review、autoCrawl、IAM、bucketには触れない。

クラウドの実行制限により実PostgreSQL/ChromiumはMacまたは通常CIで確認する。コンパイルや単体試験を実PG・実ブラウザ受入の代わりにはしない。結果と公開前手順は[今回の引き継ぎ](../history/CLOUD_TRANSFER_RELEASE_HANDOFF_2026-10-07.md)に記録する。
