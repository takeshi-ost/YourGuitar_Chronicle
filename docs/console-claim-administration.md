# Browser Console のClaim管理

ローカルのBrowser Consoleで各ClaimのVerificationをPositive（許可）・Negative（不許可）・Unverified（未確認）に変更できる。著者・現所有者・Claim種別の制限を受けない。管理者判定後は通常のOwner Verificationで上書きできない。管理者は再変更できる。

- Consoleページは、接続元とHostの両方がlocalhost/loopbackの場合にのみ、プロセスごとの管理トークンを返す。管理APIはそのトークンとローカル接続を検証する。ユーザーアカウントのadminロールではなく、現在のローカル試作環境向けの管理権限。公開サーバー・リバースプロキシ構成での認証には別途対応が必要。
- 判定・削除後はClaimから個体のスナップショットを再構築する。所有履歴のペアは一緒に変更する。Identity Correction、Specification、Ownershipの適用はPositiveのものに限定する。
- Listingが不許可でも、個体を参照するための基礎識別情報（Maker/Model/Year/Serial）は維持する。Listingの所有者・ロケーション・Finishの主張は適用しない。
- 最後の有効なListing Claimを削除する場合は、個体と関連記録も削除することをUIで明示して確認する。APIでも明示的な追加フラグが必要。それ以外は対象Claim（ペアの場合はペア）だけ削除して再計算する。
- 管理操作をclaim_admin_actionsに記録する。削除後も対象ID・操作・変更前の判定・日時は残る。復元用バックアップではない。
