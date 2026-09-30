# SNS要素の設計・実装記録

この文書はSNS追加の目論見、仕様、実装内容、検証、未実装範囲を蓄積する。後日のローカルCodexによる評価資料として保持し、以後のSNS変更も追記する。現行ブランチは `feature/observation-redesign`。

## 基本方針（2026-09-30）

ユーザーのギターとClaimを中心に、閲覧・交流を支援する。Follow / Followerはウォッチと公開範囲の関係であり、所有権、Claim作成・有効性、Verification、Observation調停、管理者権限には一切影響させない。Followは一方向であり相互Followを要求しない。

コミュニケーションの受付設定はFollowと別に扱う。Followした、あるいはされたことによって返信・DMを自動許可しない。今後Block / Muteを追加する場合も、所有権やClaim判定権限を変えず、Current OwnerによるAcquire確認などの必要な操作経路を維持する。

候補機能はFollow、フォロー一覧、ユーザー検索、フィード、通知、Response返信、メンション、交流リアクション、Block、Mute、Report、公開・接触設定、DM。最初はFollow関係と既存Followers公開範囲の接続を作る。Good / BadによるClaim評価と交流上の好意は別の意味として扱う。

## 第1段階：FollowとFollowers公開範囲

### 実装した挙動

- ログイン相当の操作ユーザーで他ユーザーのUser Profileを開くとFollowボタンを表示。登録後はFollowing、再クリックで解除。本人にはUser Settingsを表示し、自己FollowはAPIでも禁止する。
- Followers / Followingの実数を表示。人数をクリックするとモーダルでユーザー一覧を開く。名前からプロフィールへ移動できる。Close、枠外クリック、Escapeで閉じる。
- 一覧は50件ずつ表示してLoad moreで続ける。APIのlimitは1〜100、offsetは0以上。新しい関係から並べ、同時刻はユーザーID降順。
- Followersは「対象プロフィールの本人を閲覧者がFollowしている」場合に表示する。逆向きのFollowだけでは表示しない。相互Followは条件にしない。
- 生年月日、Residence、Bio、Avatarの既存公開設定へ適用する。生年月日のUser Chronicle項目にも同じ公開規則を適用する。本人は自分の項目を確認でき、Public / Members / Privateの意味は維持する。
- Avatar取得APIにも公開規則を適用する。非表示なら標準アイコンを返す。ヘッダー・Settings・Consoleの画像URLも閲覧者IDを明示する。
- GuestはFollow更新不可。本人以外のFollow更新、存在しないユーザー、BANアカウント、sourceアカウントを拒否する。重複登録・繰り返し解除は冪等。
- BAN / sourceユーザーは人数・一覧・Followers閲覧資格から除外する。関係レコード自体は保持する。Silent BANに追加の社会関係制限は設けず、既存のClaim不活性化の規則を維持する。
- Followによる通知やSocial Chronicle項目はこの段階では生成しない。

### データ・処理の境界

`app/src/ygc/db/schema.sql`に `user_follows(follower_user_id, followed_user_id, created_at)` を追加。複合主キーで重複を防ぎ、CHECKで自己Followを防ぐ。両ユーザーの外部キーと削除CASCADEを設け、逆引き用indexを追加する。起動時の既存 `init_db()` が既存DBへ追加するため、手動移行コマンドは不要。既存関係を保持した再初期化も検証する。

RepositoryにFollow登録・解除、人数・一覧、プロフィール項目の共通公開判定を追加する。Follow更新は専用テーブルだけを操作し、ClaimやEvidenceを作らず、Individual Snapshotやuser_guitarsを更新しない。Claim/Observationエンジンはuser_followsを参照しない。

| API | 内容 |
| --- | --- |
| `PUT /api/users/{user_id}/following/{target_id}?viewer_id=…` | 操作ユーザー自身のFollowを登録 |
| `DELETE /api/users/{user_id}/following/{target_id}?viewer_id=…` | 同じ関係を解除 |
| `GET /api/users/{user_id}/connections/{followers\|following}?limit=50&offset=0` | 公開用のid / display_name / account_typeだけを返す |
| `GET /api/users/{user_id}/profile?viewer_id=…` | socialのfollowers_count / following_count / is_followingを追加、項目を公開範囲で絞る |
| `GET /api/users/{user_id}/chronicle?viewer_id=…` | 誕生日のFollowers公開に対応 |
| `GET /api/users/{user_id}/avatar?viewer_id=…` | 共通公開規則で画像または標準アイコンを返す |

UIは既存のTopPage共通シェルを維持し、User Profileの統計と操作欄へ追加する。Follow後は表示中のプロフィールを再取得し、公開範囲の変化を反映しつつProduct Detailの選択個体を保持する。一覧モーダルの古い通信結果は、別の一覧を開いた後には反映しない。

### ローカル試作の認証境界

`PrototypeIdentity`を通して操作ユーザーを解決するが、viewer_idは本人確認ではない。IDを任意指定できるローカル試作であり、公開サービスの認証・機密保護を実装したことにはならない。既存のユーザー詳細API等にも公開範囲を迂回できるローカル管理上の経路がある。この段階で独自の本認証は作らない。

GCP移行時はIdentity Platformで検証したprincipalからuser_idを決定し、ブラウザ指定viewer_idを権限根拠にしない。Follow更新とプロフィール/Chronicle/Avatarの閲覧者解決を置き換え、既存API全体の情報公開経路も評価する。Followersは交流上の閲覧条件であり、DB変更権限を付与するロールにしない。

### 検証と評価観点

`app/tests/test_user_follows.py`で方向性、重複・解除、Guest・別ユーザー・自己Followの拒否、プロフィール/Chronicle/Avatarの公開・非公開への変化、一覧の返却項目とページ指定、BAN/sourceの除外、旧DBへの追加を確認する。Follow前後にindividuals / claims / claim_evidence / user_guitarsが変化せず、Current OwnerのVerification対象集合も変化しないことを確認する。

既存のUser Profile、Claim Verification、Ownershipテストと、プロフィール更新・共通Product Detail・Console User DetailのJavaScript回帰検証も実行する。実ブラウザではFollow→表示変化→Followers一覧→解除の往復を確認する。検証結果：Python全体193件通過・2件スキップ（画像認証の追加依存関係がない検証環境のため）。JavaScriptではFollowの選択保持・通信失敗時の再操作2件、既存プロフィール更新5件、共通Product DetailとConsole User Detailの検証が通過。ChromiumでFollow→Followers限定Bioの表示→Followers一覧→解除による非表示、本人・Guestのボタン非表示を確認し、JavaScript例外は0件だった。実ブラウザ検証は隔離DBを使用し、実データには変更を加えていない。

後日の評価では、自己Claim判定禁止や所有権移行の不変条件を維持すること、Followers条件の向き、公開情報の漏れ、通信失敗時の再操作、一覧の大量データ対応、本認証への交換可能性を確認する。

## 次段階の未実装項目

フィード・Follow通知・ユーザー検索拡張・接触設定・Block / Mute / Reportは未実装。DMは後述の第3段階で追加した。フォロー一覧の公開範囲選択、非公開アカウントのフォロー承認、解除時の確認、ユーザー削除・BAN解除後の関係復帰方針も今後の検討対象。現段階では関係一覧は公開用情報として返す。

## 第2段階：New DiscoveryのCurrent Owner表示（2026-09-30、後述の訂正で置換）

### 目論見と決定

専用のFollowingフィードは現時点では作らず、既存New Discoveryからユーザーの関係を把握できるようにする。表示対象はListing作成者や最新Claimの作成者ではなく、Observation結果を反映したCurrent Owner。操作ユーザーからCurrent OwnerへのFollowが存在する場合だけFollowingを表示する。逆向きのFollows youは表示しない。

### 実装

`GET /api/new-discoveries?viewer_id=…`で仮認証境界を通して操作ユーザーを解決し、現在Ownerの公開用ユーザーID・Display Name・Following真偽を返す。既存の最大200個体、並び順、活動の選出規則は維持する。取得SQL内でOwnerとFollow関係を照合し、個体ごとの追加問い合わせを避ける。Individual/Claim/Ownershipの更新は行わない。

New Discoveryの各行にCurrent Owner名へのUser Profileリンクと、該当する場合のみFollowingタグを追加する。Owner名のクリックは行の個体選択に伝播させず、プロフィールへ移動する。個体名など他の部分のクリックは従来通りProduct Detailを開く。長い個体名は省略し、Ownerとタグのスペースを確保する。テキストはHTML escapeする。

Guestでも実ユーザーのOwnerリンクは表示し、Followingは表示しない。プロフィール訪問は既存のMembers only規則に従う。Seller / Unknownなど実ユーザーでないOwner、source、BAN・Silent BANのOwnerにはSNSリンクを付けない。無効化された閲覧者のFollow関係も表示判定に使わない。未承認Acquireの申請者には切り替えず、承認による所有者移行後に新Ownerへ切り替える。

### 検証

`test_discovery_following.py`で逆向きFollow、閲覧者ごとの結果、Guest、未承認Acquire、譲渡承認、Follow解除、Release後のUnknownを確認する。`test_discovery_owner_ui.cjs`でOwnerリンク、HTML escape、Following条件、行クリックの伝播防止を確認する。実ブラウザでOwnerリンクと個体選択の分離を検証する。検証結果：Python全体194件通過・2件スキップ（画像認証の追加依存関係がないため）。JavaScript検証と共通Product Detail検証が通過。隔離DBのChromiumでFollowing表示、Owner名クリックの実プロフィール遷移、行クリックの個体選択との分離、Guestでのタグ非表示を確認。JavaScript例外は0件。

Follow先の更新フィード・通知は引き続き未実装。viewer_idは引き続きローカル試作の識別入力であり、本認証ではない。GCP移行時の境界は第1段階と同じ。

## 第2段階の訂正：全体の新着とFollow先の活動を混在（2026-09-30）

### 意図の訂正

前項は意図を誤って解釈した実装だった。求められているのは全体のギター・Claim新着を残し、その中に「Follow先ユーザーが対象ギターに何をしたか」という活動を混ぜること。表示対象はCurrent Ownerではなく行為の実行者。OwnerがFollow先だから第三者の活動にもFollowingを付ける挙動は廃止する。Git履歴は戻さず、訂正コミットで前項を置き換える。

### 現行実装

- 全体の既存新着最大200個体を取得し、Follow先の公開活動を別に直近最大200件取得して、記録日時の最新順に混ぜる。通常の新着をFollow条件で絞り込まない。最大400行となる。
- 対象活動はClaimの作成とGood / Bad投票。ユーザー登録・プロフィール更新・誕生日、Favorite、Follow、Verification変更、コメントは今回の対象に含めない。既存のVerification更新は実行者履歴を記録しないため、Claim.updated_atから誰の行為かを推測しない。
- Claim作成はcreated_at、投票はupdated_atで並べる。Claimの過去の発生日で新着順位を変えない。投票は現在保存されている状態の最終更新であり、全操作の履歴ではない。
- 通常新着の最新ClaimとFollow活動が同じClaimの場合はFollow活動の1行へ統合する。それより古いFollow先のClaimも、直近活動の範囲内で表示できる。他人の所有ギターへのClaim、未承認Acquireも、公開されている活動として扱い、所有移転を意味する表示にはしない。
- 活動行は「実行者名 · Following — added a Specification Claim to ギター名」等の英語表記。実行者名はUser Profileへのリンク、ギター名と行の他部分はProduct Detailへの導線。リンクのクリックを個体選択へ伝播させない。
- Current Ownerの名前・Followingタグは通常新着行から削除する。Guestは全体新着のみ。Follow方向は操作ユーザー→実行者。BAN / Silent BAN / sourceの実行者は対象外、BAN / sourceの閲覧者はFollow活動を取得しない。inactive Claimと非公開扱いの作成者のClaimへの投票も除外する。
- ギターDB、Claimの有効性・Verification、Observation、所有権の処理には変更を加えない。専用フィード枠や新規の活動保存テーブルは作らない。

### 実装・検証の範囲

Repositoryのlist_following_activityはClaimと投票を一括照合し、取得件数を制限する。New Discovery APIで全体新着との統合・同一Claim重複除去を行う。UIは実行者リンクと行動文を描画する。第2段階のCurrent Owner基準テストは、実行者基準のテストへ置き換える。

テストでは他人の所有ギターへのFollow先Claim、逆方向Follow、全体新着の維持、最新Claimの重複除去、別ユーザーが後からClaimを追加しても古いFollow活動を保持すること、投票、Guest、Follow解除、Silent BAN除外を確認する。JSでは実行者リンク、HTML escape、クリック伝播防止、行動文を検証する。検証結果：Python全体194件通過、2件スキップ（画像認証の追加依存関係がないため）。活動表示のJS検証と共通Product Detail検証が通過。隔離DBのChromiumでFollow先の第三者ギターへのSpecification追加と通常新着の混在、活動者プロフィールへの遷移、行クリックとの分離、Guestの通常新着のみ表示を確認。JavaScript例外は0件。

## 第3段階：Claimから独立したDM（2026-09-30）

### 目論見・初期範囲

Claim関連の変更は慎重に進めたいという要望から、コメント・返信を先行せず、ユーザー間のテキストDMを追加する。DMは交流データであり、Claim / Evidence / Verification / Observation / Ownershipと独立させる。内容をClaimの根拠に自動採用せず、New Discoveryにも出さない。

初期版は1対1、テキストのみ、1通2000文字まで。Followの有無を送受信権限に使わず、相互Followも要求しない。有効な通常アカウント間で開始できる。DM受付設定・Block・Mute・Reportは後続の設計対象とし、まだ搭載しない。

### UI

- 他ユーザーのUser ProfileにMessageボタンを追加し、対象者との会話を開く。本人には表示しない。
- TopPage / User ProfileのヘッダーにあるMessagesボタンを有効化し、未読総数を表示する。既存のClaim通知と別に管理する。
- モーダル左側に会話一覧と相手名・直近本文・未読件数、右側に選択した会話と入力欄。相手名からUser Profileへ移動できる。自身の送信を右側へ寄せ、受信と区別する。
- 直近50通を古い順に表示し、Load older messagesで50通ずつ追加。会話一覧も50件ずつ追加読込する。Refreshで他タブ・別ユーザーからの新着を取得する。リアルタイム配信・自動ポーリングは行わない。
- 表示した会話の受信メッセージを既読にし、未読総数・会話別件数を更新する。読込後に届いた未表示メッセージを既読にしないよう、表示済みの最大IDまで更新する。
- 本文はHTML escapeし、改行を保持する。添付画像・リンクの自動展開・HTML入力は非搭載。
- 送信中は入力とSendを無効化して二重クリックを防ぎ、失敗した場合は入力を残して再操作可能にする。会話切替時の古い読込結果は新しい会話へ反映しない。
- Close、Escape、枠外クリックで閉じる。狭い画面では会話一覧と本文を縦に配置する。GuestにはMessages操作を提供しない。

### DB・API

`direct_messages(id, sender_user_id, recipient_user_id, body, created_at, read_at)`を追加。自己送信の禁止、本文長、ユーザー外部キーをDB制約でも確認する。受信者・既読・ID、送信者・受信者・IDのindexを追加する。起動時のinit_dbで既存DBに自動追加し、再初期化で既存メッセージを保持する。

会話は送信者と受信者の組から導出し、新規のConversationレコードを先に作らない。GETは保存内容を返すだけで既読にせず、既読更新を別APIにする。

| API | 内容 |
| --- | --- |
| `GET /api/dm?viewer_id=…&limit=50&before_id=…` | 操作ユーザーの会話一覧・未読総数・次ページcursor |
| `GET /api/dm/users/{peer_id}/messages?viewer_id=…&limit=50&before_id=…` | 操作ユーザーと指定相手の会話だけ。古い順の本文と次ページcursor |
| `POST /api/dm/users/{peer_id}/messages?viewer_id=…` | bodyフィールドのテキストを、解決された操作ユーザーから送信 |
| `POST /api/dm/users/{peer_id}/read?viewer_id=…` | through_idまでの、自分宛て・指定相手からの受信だけを既読にする |

一覧・履歴はlimit 1〜100、cursorは正のID。相手や操作ユーザーが存在しない、BAN、sourceなら拒否し、自己送信・空白のみ・2000文字超も拒否する。会話一覧・未読件数からBAN / sourceの相手を除外するがデータは削除しない。Silent BANは既存のClaimに対する措置なので、DMに追加の不活性化は設けない。ユーザー削除時には外部キーCASCADEで関係メッセージも削除する。

### 仮認証・将来の交換箇所

全DM APIはPrototypeIdentity経由で操作ユーザーを解決し、操作ユーザーが参加する組だけを照会・更新する。送信者IDを本文から受け取らない。第三者として自分のIDを指定した場合は他の2人の会話を取得・既読化できない。

ただしviewer_idはブラウザからの仮入力であり、他人のIDを名乗れない認証ではない。このローカル試作を本番の秘密通信として扱わない。GCP移行時はIdentity Platformで検証したprincipalからuser_idを決定し、全DM APIの照会・更新へ渡す必要がある。既存のfail-closedクラウド境界は維持する。

本文はローカルSQLiteに通常のテキストで保存し、エンドツーエンド暗号化・暗号鍵管理は非搭載。外部通知・メール送信・添付ファイル・管理者閲覧UIも作らない。通信失敗時の自動再送は行わず、送信済み応答が失われた場合の再送重複を防ぐrequest IDも未搭載。

### 検証・評価観点

`test_direct_messages.py`で送受信・返信、未読と既読cursor、第三者の会話非表示・既読不可、Guest・自己送信・空白・文字数制限・不存在・BAN/source、ページング、既存DBの自動追加・保存保持を確認する。DM前後でindividuals / claims / claim_evidence / user_guitars / notifications / user_followsが変化しないことを確認する。

`test_direct_message_ui.cjs`で送信後の入力消去・会話更新、失敗時の入力保持と再操作、送信中の二重送信防止を検証する。実ブラウザは隔離DBで2ユーザーの送信・返信・未読・既読、HTML escape、プロフィール導線を往復確認する。検証結果：Python全体197件通過、2件スキップ（画像認証の追加依存関係がないため）。DM UIのJSテスト3件、既存プロフィール更新5件、Console User Detailと共通Product Detail検証が通過。隔離DBのChromiumで2ユーザーの送信・返信・未読→既読、HTML escape、第三者の受信箱非表示、500px幅の表示を確認。JavaScript例外は0件。

後続の評価では、Identity Platformへの交換、DM受付設定、Block / Mute / Report、保存期間・ユーザー削除方針、送信頻度制限、送信request ID、リアルタイム更新を検討する。所有権・Claim権限の判定とは接続しない。
