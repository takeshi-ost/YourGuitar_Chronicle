# Cloud Media Claim 引き継ぎ（2026-10-07）

## 作業の境界

- リポジトリ：`takeshi-ost/YourGuitar_Chronicle`
- 正確なbase：`be896b37a56683bfa4e79255666109f5834e89f6`（PR55統合後）
- ブランチ：`feat/cloud-media-claims`
- 別checkoutで実装。以前のClaim投稿checkoutとcheckpointは保持。
- このcheckpointではcommit・push・PR・merge・deployを実施していない。

## 内容と保持した意味

認証済み本人のMedia Claim投稿（新規写真1〜10枚）、キャプション・日付の編集、ソフト無効化、本人の提出一覧と写真閲覧を追加。現在Ownerの既存判定画面へprivate写真を接続し、添付全体を確認できない状態からの画面上の判定操作を止める。写真は1枚8 MiB・800万画素、合計24 MiBまでのJPEG / PNG / WebP。EXIF補正・メタデータ除去後の最長辺2048 px JPEGを保存する。詳細は[Cloud Media Claim](../migration/CLOUD_MEDIA_CLAIMS.md)。

通常のMedia作成・通知・Observation再評価を共有Repositoryに委譲する。現在Ownerの投稿はPositive、第三者はUnverified。通常の自己判定は禁止。正本アカウント・投影・関連者・Service Modeと保守／Crawl排他を従来どおり使う。権限は制限付きPostgreSQL runtime roleのままで、schema migrationやGRANT変更は不要。

添付は不変。編集対象はキャプション・日付だけで、Verificationと管理者判定の来歴を保持する。Deactivateはinactive化のみで写真を物理削除しない。投稿者は自身のinactive写真も確認できるが、Ownerの通常閲覧からは外れる。所有移転・BANで失う写真判定権限を古いOwner確認で使用できない。

Claim内容とEvidence／画像のID・順序・固定保存参照をrevisionへ束縛し、同一時刻編集、添付変更、判定変更、古い写真取得を拒否する。写真はBearer認証で取得してBlob URLとして表示し、閉じる／アカウント変更／移動で破棄する。

実バケットは触らず、テスト内Storageはすべてメモリ上の合成fixture。保存が確実に失敗した試行だけ新規オブジェクトを補償し、コミット結果不明なら参照切れを避けて保持する。画面は自動再送せず、下書き・選択画像を残して最新一覧の確認と明示的な再試行を求める。

## 公開・運用上の判断

- Public catalogは変更なし。PositiveのMediaも写真・本文・投稿者・Storage参照を公開しない。
- 新しいprivate入口は本人と、その時点の通常判定権限を持つCurrent Ownerのみ。Adminの他人の画像閲覧は従来の明示的な管理用入口。Adminだから通常本人編集を迂回できるわけではない。
- 所有審議写真をMediaへ転用しない。入力は新規ファイルのみで、ユーザー指定参照や既存Evidence IDを受け取らない。別ClaimのEvidenceとして共有された画像も拒否する。
- 公開写真の同意・公開範囲、写真の追加／差し替え、物理削除・保持期間・孤立画像回収、永続的なExactly-once作成キーは今回決めない。
- 実データ・認証・DB schema/rows・IAM・bucket・実写真・Service Mode・Review・autoCrawlは変更していない。既存のOffline v13 / Review OFF / autoCrawl OFFを維持する作業境界。

## 検証と残りの受入

最終checkpointでPython 1,261件、JavaScript 358件が成功。依存固定・schema再生成整合・追加PG／ブラウザスイートのPythonコンパイル・diffチェックも成功した。`validation.log`に集計結果を保存する。独立レビューの指摘を受け、BAN済みMediaのOwner一覧／直接判定の一致、Owner画面の明示選択1Claimだけの写真取得、キャンセル後の一時ファイル確実な解放、サーバー内の同時処理上限を修正・追加した。再レビューで未解決のblocking findingはなく、独立した追加確認はPython 144件・Node 112件が成功。

実PostgreSQL・Chromiumはこのクラウド作業環境で未実行。禁止された起動やインストールは再試行していない。使い捨てPG契約スイートと完全合成のブラウザスイートを用意し、統一runnerへ登録した。PG fixtureのsequence初期化・fault injectionはDB ownerだけで行い、サービス操作は制限付きruntime roleを使う。

同一checkpointをMacまたは通常CIへ適用し、次を実施する。実ステージングへfixtureを投入しない。

```sh
python scripts/check_dependencies.py
python scripts/build_postgres_schema.py --check
python scripts/run_tests.py --browser --postgres-bin /path/to/postgresql18/bin
```

通常CIの既存PostgreSQLサービスでは`--postgres-port 5432`。Mac／CIでは1〜10枚投稿、編集・無効化、photo revision競合、Author／Owner／Adminの権限差、所有移転・BAN、Read Only／Offline、画像取得中の閉じる・個体移動・SignOut、戻る／進む、通信結果不明、狭い画面の画像表示を確認する。単体成功やスイートのコンパイルを実PG／実ブラウザ合格とは扱わない。

公開・PR作成・統合・配置は、この受入結果と個別承認の後。後続移植はEvent、Transfer／Releaseと受諾・係争、Listing訂正。公開ギャラリーは写真の公開同意を決めてから。
