"""Operator-curated themes; users choose IDs, never supply CSS or asset URLs."""

THEMES = (
    ("dark_default", "Dark Default"),
    ("light_default", "Light Default"),
    ("sunburst_3ply", "Sunburst&3ply"),
    ("butterscotch_black", "Butterscotch & Black"),
    ("olympic_white_mint", "Olympic White & Mint"),
    ("surf_green_white", "Surf Green & White"),
    ("sonic_blue_white", "Sonic Blue & White"),
    ("fiesta_red_white", "Fiesta Red & White"),
    ("black_pearl", "Black & Pearl"),
    ("goldtop_cream", "Goldtop & Cream"),
    ("cherry_red_black", "Cherry Red & Black"),
    ("vintage_white_gold", "Vintage White & Gold"),
    ("lake_blue_pearl", "Lake Blue & Pearl"),
)
THEME_IDS = frozenset(key for key, _ in THEMES)
