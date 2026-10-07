# Cloud Claim 投稿・編集 引き継ぎ（2026-10-07）

## 作業の境界

- 元リポジトリ：`takeshi-ost/YourGuitar_Chronicle`
- 正確なbase：`1bca3c8b34a48cfb27703811ba8e441dc23dc680`（PR54統合後）
- 作業ブランチ：`feat/cloud-claim-posting`
- 新しいcheckoutで実装。以前の作業フォルダ・checkpointは保存。
- このcheckpointではcommit・push・PR・merge・deployを実施していない。

## 内容

認証済み投稿者の Specification / Repair と Incident（Damage / Lost / Theft）の作成・編集・無効化を、既存 Claim / Observation と PostgreSQL の認可トランザクションへ接続した。公開Product Detailから選択を認証後まで保持し、自分の内容・状態・更新日時を確認できる。Owner の既存判定画面も、typed項目込みの改訂トークンとReadOnly能力で安全側に接続する。

Listing、Identity Correction、Ownership、Event、Mediaはこの汎用APIの対象外。自分のClaimだけを編集でき、Adminにも他人の投稿を通常編集する権限は付かない。通常Owner判定は既存規則を使う。詳細は[Cloud Claim投稿・編集](../migration/CLOUD_CLAIMS.md)。

公開APIの返却項目はPR54から変更していない。画像・自由記述・投稿者・所在地・私的Evidenceを公開する経路は追加していない。公開可能な固定Specification項目は従来の承認条件に従う。

編集でVerificationをリセットしない既存ローカル挙動を維持した。このため、第三者の承認済みClaimは編集後もPositiveのまま。UIで更新日時とこのルールを明示する。再承認ポリシーを変更するなら別の仕様決定として扱う。

## 保持した実環境状態

実データ・実認証・Cloud SQLのschema/row・Service Mode・Review設定・IAM・bucket・保存画像には触れていない。ステージングのOfflineとReview OFF、取消済みfixtureと画像は作業対象外。

## 確認結果

最終checkpointでPython 1,198件、JavaScript 301件が成功。依存固定、schema再生成整合、追加PG／ブラウザスイートのPythonコンパイル、diffチェックも成功した。独立レビューの指摘を修正し、残るblocking findingはない。同梱の `validation.log` とmanifestに検証結果・ファイルhashを記録する。

実PostgreSQL／Chromiumは未実行。仮想環境で拒否されているサーバー／ブラウザ起動は再試行していない。これらはMacまたは通常CIでの次の受入確認であり、単体成功を代替の実機合格として扱わない。

新規のPG・ブラウザ検証は使い捨てfixtureだけで用意し、通常の統一runnerへ登録済み。Macまたは通常CIで同じcheckpointへ適用して実行する：

```sh
python scripts/check_dependencies.py
python scripts/build_postgres_schema.py --check
python scripts/run_tests.py --browser --postgres-bin /path/to/postgresql18/bin
```

CIの既存PostgreSQLサービスを使う場合は `--postgres-port 5432`。実ステージングへfixtureを投入しない。

## 次の移植単位

1. 同一checkpointのMac/CI実PG・Chromiumと、狭い画面を含む表示確認。投稿・編集・競合・無効化、アカウント変更、戻る／進む、ReadOnly/Offline、既存Acquire導線の回帰を確認。
2. Event / Media は非公開保存・配信／公開同意の境界を確定してから。所有審議のEvidence写真を公開画像へ転用しない。
3. Transfer / Release、受諾・取消・係争の認可を既存の所有権遷移テストとまとめて移植。Inheritの新規作成は廃止済み。
4. Listing訂正は専用Identity Correction導線として移植。通常編集へ混ぜない。

作成の通信結果が不明な場合は下書きを保持し、提出一覧の確認と明示的な再試行の選択を求める。自動再送しない。永続的な冪等キーによるExactly-once作成は今回追加していない。公開と実所有受入試験は別の承認段階。
