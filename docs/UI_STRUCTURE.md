# UIの構造

ページのDOM、共通部品、ページ固有の処理を分離する。フレームワークは追加せず、既存のHTMLとJavaScriptを使う。

| 層 | ファイル | 担当 |
| --- | --- | --- |
| ページ構造 | `static/*_html.html` | DOM、フォーム、アセットの読込。TopとProfileは同じテンプレート |
| ページ別処理・スタイル | `static/pages/{console,user-view,user-edit}.{js,css}` | API通信、権限に応じた操作、ページ状態、ページレイアウト |
| オーバーレイ管理 | `static/overlays.js` | 独自モーダル、Consoleのnative dialog、画像アルバムの開閉とフォーカス |
| 個体詳細 | `static/product-detail.js` | Specification・Chronicleの基本レイアウト、Claim順、ギャラリー、アルバム、アコーディオン |
| 共通部品CSS | `static/ui-components.css` | モーダル、画像アルバム、共通操作色、ボタン・入力欄。ダーク／ライトのCSS変数で指定 |
| テーマ | `static/themes.css` | テーマ色・背景・ブランド表示 |
| リスト操作 | `static/list-navigation.js` | 選択リストの上下移動、表示行数、日付入力の上限。オーバーレイ表示中は背景を操作しない |

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

ヘッダー・アカウント操作、フォーム送信と画像検証、フォーム固有のレイアウトにはページ間の重複が残る。今回の分離によって共通化が全て完了したわけではない。権限や送信先の違いを維持し、操作上の共通部分を順次抽出する。

## 共通配色とレイアウト

操作部品はテーマのサブウィンドウの明暗に合わせたダーク／ライトの共通配色を使う。ボタンの役割は`data-ui-action`（primary / close / neutral / danger）で指定する。テーマ追加時は共通パレットも選択する。詳細は [USER_THEMES.md](USER_THEMES.md)。

- Notificationsは共通モーダル。確認済みの行はモーダル背景色、未確認は別の面色と左線で区別する。
- Ownership Requestsは本人ProfileのUser Settings横。ヘッダーのCheck Requestsは申請中または未確認の結果がある場合だけ表示する。
- Unanswered RequestsはTop Page / Profileの先頭。コンパクトな青緑背景・白太字・明るいミント色の枠を全テーマで共用する。
- 追加を促す所有申請・Claim追加・新規ギター追加の操作には二重線の共通枠を付ける。
- Product Detail内の所有申請・Claim追加ボタンとClaimカードは同幅・同位置とし、左右の余白を揃える。
- Top PageのStatisticsはModel Distributionから始める。デスクトップのページ内リンク移動では、そのカード上端を固定Product Detail上端に合わせる。
- `data-count-items`付きの一覧見出しには、表示中の行数を小さな`N items`として下端を揃えて表示する。空状態の行は数えない。
- 画像アルバムは1枚でも中央の画像列を使用し、前後ボタン非表示時に画像が狭いナビゲーション列へ入らないようにする。
