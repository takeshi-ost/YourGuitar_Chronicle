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

フィード・Follow通知・ユーザー検索拡張・接触設定・Block / Mute / Report・DMは未実装。フォロー一覧の公開範囲選択、非公開アカウントのフォロー承認、解除時の確認、ユーザー削除・BAN解除後の関係復帰方針も今後の検討対象。現段階では関係一覧は公開用情報として返す。
