# Your Guitar Chronicle の変更時に確認すること

Ownership、Verification、Claimの有効性、BAN、Merge、Observation、User ProfileのOwned / Formerly Ownedに触れる変更の前に、[Claim中心のデータ構造](docs/CLAIM_CENTERED_ARCHITECTURE.md)の「所有権と判定権限の相互作用（設計上の不変条件）」を読む。

Current Ownerによる他ユーザーClaimの判定、自己Claimの判定禁止、Acquire承認前後の所有状態、譲渡後の判定権限の移動は**別々の機能ではなく、組み合わさって成立する性質**として扱う。関連変更では、文書末尾の遷移例を実装とテストの両方で確認する。管理者による強制判定は通常ユーザーとは別経路として確認する。
