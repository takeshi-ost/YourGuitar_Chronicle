# Cloud Storageの接続基盤と実環境確認

2026-10-04。コンテンツ用とアカウント用の非公開バケットへ接続するアダプターを追加した。画像のアップロード／配信API・既存DBの画像参照・バックアップ保存への接続は後続作業であり、本段階で全画像機能を移行したとは扱わない。

## 保存先と参照

`YGC_MEDIA_BACKEND=gcs`、`YGC_CONTENT_BUCKET`、`YGC_ACCOUNTS_BUCKET`を明示する。2バケットは別名を必須とし、Cloud Runの実行資格で公式SDKを利用する。ローカルファイルへ代替しない。Storage Emulator設定を拒否する。Cloud Storage依存をstorage extraとして明示し、固定版3.16.0を維持した。導入スクリプトには `--storage` を追加した。

| scope | ステージングの保存先 | 意味 |
| --- | --- | --- |
| content | `your-guitar-chronicle-staging-content` | ギター・投稿・申請・根拠等の画像実体 |
| accounts | `your-guitar-chronicle-staging-accounts` | アカウントのアバター等の実体 |

両バケットは東京、プロジェクト番号891242348530、Uniform bucket-level access有効、Public access prevention強制、Soft delete 7日を確認した。既存 `ygc-staging-app` の対象バケット上のobjectUserを使い、新たな公開権限・SA鍵を作らない。

保存はサーバー生成UUIDのキーへ `if_generation_match=0` で作成し、既存オブジェクトを上書きしない。参照はscope・キー・generation・size・content_typeを保持する専用型。URLやユーザー指定のファイル名はキーに使わない。取得・削除は保存時のgenerationを指定し、最新世代へのすり替えを防ぐ。CRC32Cを使い、取得前にサイズ・MIME・Content-Encodingを確認する。バイト列は最大25MiB。参照先・サイズ等が不一致なら拒否する。

この型は今後DBへ接続するための契約であり、既存のmedia_storage_pathへ自動変換しない。SDK資格があることは画像閲覧のYGC権限ではない。呼出側がClaim・所有者・当事者・公開設定・サービスモードを確認し、アップロード時の画像形式・画素数・EXIF等の正規化も実施する。アダプターだけでは画像内容の有効性を判定しない。署名URL・公開ACL・任意のオブジェクト取得APIは設けない。

## 状態確認と読み書き確認を分離

`GET /api/admin/operations/storage` は、確認済みメール・Accounts正本の有効なAdmin・操作中の資格再確認を必要とする。返すのはscopeごとのavailable / unavailableとread_onlyの表示だけ。バケット名・オブジェクト名・内部エラーを返さない。専用の無害な `_ygc/storage-read-check-v1` を読み、内容とサイズを確認する。エラーはscopeごとにunavailableとする。

BrowserConsoleのService statusにコンテンツ用とアカウント用を別々に表示する。Refreshは読み取りだけ。現在の読み取り成功は、将来の画像アップロードや復元がすべて成功する保証ではない。Storage障害でメンテナンス解除経路を封鎖しない。

`python -m ygc.storage_probe_job --confirm-project PROJECT` はIAMのJob実行権限が必要な専用確認入口。単一タスク、retry 0で実行する。HTTPサービス内実行・プロジェクト確認不一致・Emulatorを拒否する。各scopeに一意な一時オブジェクトを保存し、取得内容・上書き拒否・generation指定削除・削除後の取得拒否を確認する。最後に読み取り確認用マーカーを作る。マーカーが既存なら上書きせず内容を確認する。ログは結果だけで資格情報・ユーザー情報を出さない。

成功時に一時オブジェクトは削除され、無害なマーカーだけが残る。Soft deleteによる7日の保持は通常の削除にも適用される。失敗時は世代が確認できた一時オブジェクトだけを削除し、他のデータへ広範な削除をしない。通信断で作成結果が不明なオブジェクト等の孤立ファイル回収は今後の運用設計対象。

## 検証と残作業

Python577件・JavaScript71件・共通ブラウザ・実PostgreSQLの検証が通過。Storageではscope分離、同名作成拒否、古い参照による置換オブジェクトの取得／削除拒否、不正キー・世代・サイズ、過大データ、メタデータ不一致、確認用Jobの再実行、マーカー破損時の上書き拒否を検証した。状態APIのAdmin資格再確認・書込禁止、Consoleでscopeごとの成功／失敗表示も確認。単体検証はSDK操作を代替し、実環境Jobとは区別する。

後続作業はPostgreSQLのメディア参照、アップロード・権限付き配信、画像正規化、DB更新失敗時の補償処理、非公開根拠の閲覧権限、対象別バックアップ／復元・リセットとの世代整合、Crawl／GPTの画像処理への接続。

公式資料：[Blob操作](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob)、[世代条件](https://docs.cloud.google.com/storage/docs/request-preconditions)。

## ステージングの実配置

Cloud Build `e08d0cb9-65ba-4968-a990-172edfc32067` が成功。イメージ `account-api@sha256:36fc6d18c327ebb3e4ab54c2369132f9fa73484bde090dc54ae6083fe1bc580c` を使用。

専用Job `ygc-staging-storage-probe` を、既存アプリSA・1 CPU / 512 MiB・単一タスク・retry 0・timeout 300秒で配置した。DB socket・DB Secretは渡さず、Schedulerや公開Invokerも追加しない。実行 `ygc-staging-storage-probe-s8zsw` が成功し、両scopeで保存・読み戻し・上書き拒否・世代指定削除を確認した。これはエージェントによる実バケット接続試験であり、利用者の画像アップロード操作試験ではない。

認証／Consoleサービスをリビジョン `ygc-staging-accounts-00006-ppj` へ配置した。実URLのConsole・アセット・DB readyが200、Storage状態APIの無認証アクセスが401。公式SDK・匿名時の管理欄非表示・デスクトップ／モバイルの表示を確認し、配置前後でOfflineを維持した。Accounts投影・初回Admin用Jobは今回のイメージへ更新していない。
