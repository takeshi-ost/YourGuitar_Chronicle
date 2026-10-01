# UIの構造

ページのDOM、共通部品、ページ固有の処理を分離する。フレームワークは追加せず、既存のHTMLとJavaScriptを使う。

| 層 | ファイル | 担当 |
| --- | --- | --- |
| ページ構造 | `static/*_html.html` | DOM、フォーム、アセットの読込。TopとProfileは同じテンプレート |
| ページ別処理・スタイル | `static/pages/{console,user-view,user-edit}.{js,css}` | API通信、権限に応じた操作、ページ状態、ページレイアウト |
| オーバーレイ管理 | `static/overlays.js` | 独自モーダル、Consoleのnative dialog、画像アルバムの開閉とフォーカス |
| 個体詳細 | `static/product-detail.js` | Specification・Chronicleの基本レイアウト、Claim順、ギャラリー、アルバム、アコーディオン |
| 共通部品CSS | `static/ui-components.css` | モーダルの外枠、画像アルバム。ページ差はCSS変数で指定 |
| テーマ | `static/themes.css` | テーマ色・背景・ブランド表示 |
| リスト操作 | `static/list-navigation.js` | 選択リストの上下移動。オーバーレイ表示中は背景を操作しない |

## モーダルを追加・変更するとき

`YGCOverlays.open(elementOrId, options)` / `close(elementOrId)` を使い、各画面から直接 `classList` で開閉しない。フォームの初期値・送信・権限判定はページ側に置く。`options` には `opener`、`initialFocus`、`onClose` を指定できる。

- Escapeは最前面だけを閉じる。モバイルの背後のProduct Detailへ同じEscapeを伝えない。
- Tab / Shift+Tabとプログラムによるフォーカス移動を表示中のダイアログ内に限定する。
- 開く前のフォーカスとbodyのoverflowを保持し、最後のモーダルを閉じたときに復帰する。
- 重ねて開いたモーダルの親を閉じる場合は子も閉じる。個別の後処理は`onClose`へ置く。
- ダイアログには見出しに対応する`aria-labelledby`または`aria-label`を付ける。未指定の場合は見出しからラベルを補う。
- フォームの業務処理や所有者の判定権限を共通モーダル管理に持ち込まない。

Console用トークンの埋込みだけは従来どおりサーバー生成HTML内に置く。公開されるページJSにはトークン値を埋め込まない。`/assets/pages/{filename}` は6ファイルだけを許可し、パッケージ設定にも含める。

## 検証

既存のJavaScriptテストは `app/tests/page_source.cjs` でページ固有アセットを読み込み、表示・操作の回帰を確認する。Pythonテストはアセットの配信と許可リストも確認する。

`app/tests/browser_ui_components.py` は明示実行するPlaywrightテスト。実行先はuser ID 1と画像付きindividual ID 1のある検証専用サーバーを使う。既存レコードは変更しない。`YGC_BROWSER_URL`、`YGC_BROWSER_EXECUTABLE` で接続先とChromium実行ファイルを指定できる。フォーカス、Tab移動、重ね合わせ、Escape、スクロール復帰、モバイルのアルバム、native dialogを検証する。

## 残る整理

ヘッダー・アカウント操作、フォーム送信と画像検証、基本ボタン・入力欄のスタイルにはページ間の重複が残る。今回の分離によって共通化が全て完了したわけではない。権限や送信先の違いを維持し、操作上の共通部分を順次抽出する。
