# User Themes

User Settings で選ぶ運営提供のテーマ。TopPage と User Settings は操作ユーザーのテーマ、User Profile はプロフィールの持ち主のテーマを表示する。Guest は Sunburst & White。Top Page / User Profile / User Settingsのヘッダー2行は全テーマ共通の暗色で固定する。Browser Consoleは固定の `block.png` ロゴを表示する。任意の CSS・画像 URL の入力は受け付けない。

| テーマ | ボディ背景 | ウィンドウ | 枠の層 |
| --- | --- | --- | --- |
| Dark Default | 濃いグレー | 黒系 | 標準 |
| Light Default | 明るいグレー | 淡いグレー | 標準 |
| Sunburst & White | アルダー風サンバースト画像 | アイボリー | 白／黒／白 |
| Butterscotch & Black | 透ける黄褐色の木目画像 | 黒 | 黒の1ply |
| Olympic White & Mint | 温かい白の単色 | ミントグリーン | ミント／黒／ミント |
| Surf Green & White | 緑の単色 | 白 | 白／黒／白 |
| Sonic Blue & White | 水色の単色 | オフホワイト | 白／黒／白 |
| Fiesta Red & White | 赤の単色 | アイボリー | 白／黒／白 |
| Rellic Black & Pearl | 激しいレリックの黒塗装・木目画像 | 白パール画像を薄く重ねる | 白／黒／白／黒 |
| Goldtop & Cream | 金色の単色 | クリーム | クリームの1ply |
| Cherry Red & Black | 赤い木目画像 | 黒 | 黒／白／黒 |
| Vintage White & Gold | 温かい白の単色 | 金色 | 金の1ply |
| Lake Blue & Pearl | 青の単色 | 白パール画像を薄く重ねる | 白／黒／白／黒 |

定義は `ygc.theme_catalog.THEMES`、見た目は `app/src/ygc/static/themes.css`、画像は同じ `static` ディレクトリにある。旧DBの `users.theme` には3種類のみを許可する CHECK 制約が残るため、追加テーマの選択は nullable な `users.theme_override` に保存し、読み取りでは優先して適用する。将来 PostgreSQL へ移行する際には1列に統合できる。

ヘッダーのロゴは `static/logos` 内のPNGを縦横比を保って表示する。Dark Default／Rellic Black & Pearl／Goldtop & Cream／Cherry Red & Black は `block.png`、Butterscotch & Black／Olympic White & Mint／Surf Green & White／Vintage White & Gold／Lake Blue & Pearl は `badge.png`、その他のテーマは `script.png` を使う。

## テーマから独立する操作部品

モーダル・メニュー・画像アルバム・入力欄は共通配色を使う。Dark Default / Butterscotch & Black / Cherry Red & Blackはダーク、それ以外はライトを選ぶ。ページ背景が暗くてもパネルが明るいテーマはライトになる。
Submit / Accept / Saveは青緑、Close / Backは背景より明度の異なるグレー、通常操作はその中間、破壊的操作は赤。テーマ装飾でこれらの役割色を上書きしない。
ヘッダーのNotifications / Messagesは通常ダーク、未読がある場合はCreate Accountと同じprimary配色にする。YOU表示は削除済み。お気に入りのハートは背景透明で文字色のみを変える。
重要情報領域は、全テーマ共通の青緑背景（#007f83）、白太字、明るいミントの枠（#c4eeec）を使用する。

## 壁紙の木目とレリック

Butterscotch & Black／Cherry Red & Blackは既存壁紙レイヤーだけをCSSで90度回転し、木目を縦方向にする。Black & Pearlは保存済みテーマID `black_pearl`を維持し、表示名をユーザー指定の`Rellic Black & Pearl`に変更する。新しい壁紙は`static/rellic-black-wood.webp`。参考画像の黒塗装が大きく剥がれた質感を内蔵image_genで生成し、WebPに変換して配置した。


Butterscotchの壁紙は1672×941px、Cherryは1254×705.75px、Rellic Blackは1152×768pxで表示する。木目は縦方向とし、非等方な引き伸ばしを避ける。広い画面では背景を繰り返す。Sunburst & Whiteの絵柄は変更しない。
