# Browser ConsoleのClaim・個体・ユーザー管理規則

具体的な画面操作・ボタン・結果は[管理操作ガイド](README.md)を参照。本書は管理操作のデータ効果と制約を扱う。

Browser Consoleはlocalhostに接続したローカル管理者向け。ページが発行するプロセス内トークンと接続元・Hostのloopback判定を管理APIで確認する。**ユーザーのadminロールや本番認証ではない**ため、外部に公開して使用しない。

## Claim管理と所有者確認

管理者は通常ユーザーと別の経路でClaimのVerificationをPositive / Negative / Unverifiedに強制変更でき、必要ならハード削除できる。ただし係争ロック・裁定済みClaimの制限は通常の管理操作にも適用され、係争の再審議経路を使う。現在のOwnerは管理者判定後でも他ユーザーのClaimを再判定できるが、自分のClaimは判定できない。変更した個体のSnapshotを再構築し、`claim_admin_actions` に管理操作を記録する。ListingをNegativeとしても個体参照に必要な基礎識別情報は残す。最後の有効なListing Claimの削除は個体と関連記録の削除につながるため、画面の明示確認とAPIの追加フラグが必要。監査記録はバックアップではない。通常操作の所有権と判定権限の連動は[Claim中心のデータ構造](../architecture/CLAIM_CENTERED_ARCHITECTURE.md)を参照。

**Unverified Acquire** は、有効な承認待ちAcquireのうち、承認によってCurrent Ownerが変わり得るものだけを数える。ペアClaimを含めて、ロールバックされるsavepoint内でSnapshotを試算する。場所だけ変わる、後続Claimで覆われる、すでに同一Ownerのものは除外する。

## 重複候補の解決

Repeatedは正規化された**メーカーとシリアルが同じ複数のDB個体群**。モデルは候補キーに含めず、シリアル一致だけで同一個体とは確定しない。モーダルで残す個体を選び、MergeまたはDeleteする。

- MergeはObservation、Claim IDとResponse / Evidence、メディア、ユーザーとの関係を残す。統合元Listingは掲載の情報を保持した`merged_listing`由来のAcquireに変換する。Positiveだった所有・識別・仕様Claimなど一部はUnverifiedに戻し、Negative判定は保持する。選んだ個体の状態をClaimから再構築する。
- Deleteは選んだ個体以外と関連DBレコードを消し、統合元の履歴を残さない。Signature Guitarの参照も調整する。画面で破壊的操作を明示確認する。

どちらも一トランザクションで実行し、操作を記録し、候補群が表示時から変わっていた場合は拒否する。画像ファイルの扱いは既存の削除方針に従う。

## User DetailとBAN

Display Name、Account Type、Residence、Bio、4項目の公開範囲、Signature Guitar、Avatar、Theme、BAN状態を編集する。DBのID、日時、画像保存パス、計算値は直接編集しない。Signature Guitarは所有中の個体に限る。BAN変更は`user_admin_actions`に記録し、関連Snapshotを再構築する。

| 状態 | 表示と適用 |
| --- | --- |
| Normal | 通常の状態 |
| Silent BAN | ClaimはDBに残るが公開Snapshot、一覧、通知などに反映しない。本人が操作用IDを選んだ画面には有効に見える試作上のプレビューを用意する。他人には本人のClaimやプロフィール上のギター関係を見せない |
| BAN | アカウントと過去のClaim・メディア・投票の公開効果を止め、今後のClaim投稿・投票も拒否する。DB上の記録は残り、Normalへ戻すと復帰する |

**注意:** 本人／他人の区別にブラウザから届くIDを使うため、現在のSilent BAN表示は安全なアクセス制御ではない。外部公開前に認証済みIDで置き換える。

## CrawlとDB運用

管理画面は各段階の件数と最新20回の実行ログを表示する。保存済み詳細の再判定、確認待ち候補一覧、DBのバックアップ・復元・初期化、Claimの旧DB移行と不足項目Backfillを提供する。確認待ち候補を画面で承認する操作は未実装。収集の数値の定義は [incremental-crawl.md](../features/incremental-crawl.md)。
