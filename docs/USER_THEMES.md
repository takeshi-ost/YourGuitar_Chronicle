# User Themes

User Settings で選ぶ運営提供のテーマ。TopPage と User Settings は操作ユーザーのテーマ、User Profile はプロフィールの持ち主のテーマを表示する。Guest は Dark Default。ヘッダーの2行は全テーマ共通の暗色で固定する。任意の CSS・画像 URL の入力は受け付けない。

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
| Black & Pearl | 黒の単色 | 白パール画像を薄く重ねる | 白／黒／白／黒 |
| Goldtop & Cream | 金色の単色 | クリーム | クリームの1ply |
| Cherry Red & Black | 赤い木目画像 | 黒 | 黒／白／黒 |
| Vintage White & Gold | 温かい白の単色 | 金色 | 金の1ply |
| Lake Blue & Pearl | 青の単色 | 白パール画像を薄く重ねる | 白／黒／白／黒 |

定義は `ygc.theme_catalog.THEMES`、見た目は `app/src/ygc/static/themes.css`、画像は同じ `static` ディレクトリにある。旧DBの `users.theme` には3種類のみを許可する CHECK 制約が残るため、追加テーマの選択は nullable な `users.theme_override` に保存し、読み取りでは優先して適用する。将来 PostgreSQL へ移行する際には1列に統合できる。

ヘッダーのロゴは同一寸法の3種類（流れる筆記体・太い連続筆記体・前傾した角張った文字）。Dark Default／Black & Pearl／Goldtop & Cream／Cherry Red & Black は太い連続筆記体、Butterscotch & Black／Vintage White & Gold／Lake Blue & Pearl は前傾した角張った文字、その他のテーマは筆記体を表示する。文字と図案は YGC 独自のデザインで、ヘッダーの共通背景色に合わせている。
