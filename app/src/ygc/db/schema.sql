PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS individuals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 manufacturer TEXT NOT NULL,
 model TEXT,
 finish TEXT,
 year TEXT,
 serial_number TEXT,
 location_country TEXT,
 location_region TEXT,
 current_owner_name TEXT,
 current_owner_type TEXT,
 current_owner_user_id INTEGER,
 current_owner_source_url TEXT,
 normalized_manufacturer TEXT NOT NULL,
 normalized_model TEXT,
 normalized_serial TEXT,
 representative_media_asset_id INTEGER,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(normalized_manufacturer, normalized_model, normalized_serial)
);
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 individual_id INTEGER,
 manufacturer TEXT,
 model TEXT,
 finish TEXT,
 year TEXT,
 serial_number TEXT,
 owner_name TEXT,
 owner_type TEXT,
 owner_profile_url TEXT,
 location_country TEXT,
 location_region TEXT,
 location_source TEXT,
 seller TEXT,
 event_type TEXT NOT NULL DEFAULT 'listing',
 actor_user_id INTEGER,
 occurred_at TEXT,
 source_site TEXT NOT NULL,
 source_url TEXT NOT NULL,
 image_url TEXT,
 source_listing_id TEXT,
 observed_at TEXT NOT NULL,
 listing_date TEXT,
 title TEXT,
 raw_text TEXT,
 serial_confidence REAL,
 extraction_version TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(individual_id) REFERENCES individuals(id),
 UNIQUE(source_site, source_listing_id)
);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 display_name TEXT NOT NULL,
 account_type TEXT NOT NULL DEFAULT 'user',
 location_country TEXT,
 location_region TEXT,
 avatar_storage_path TEXT,
 avatar_original_filename TEXT,
 avatar_mime_type TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_guitars (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 individual_id INTEGER NOT NULL,
 ownership_status TEXT NOT NULL DEFAULT 'current_owner',
 display_order INTEGER,
 acquired_at TEXT,
 released_at TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(individual_id) REFERENCES individuals(id) ON DELETE CASCADE,
 UNIQUE(user_id, individual_id)
);

CREATE TABLE IF NOT EXISTS media_assets (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 individual_id INTEGER NOT NULL,
 uploader_user_id INTEGER NOT NULL,
 media_type TEXT NOT NULL DEFAULT 'image',
 storage_path TEXT NOT NULL,
 original_filename TEXT,
 mime_type TEXT,
 captured_at TEXT,
 caption TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(individual_id) REFERENCES individuals(id) ON DELETE CASCADE,
 FOREIGN KEY(uploader_user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS claims (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 individual_id INTEGER NOT NULL,
 observation_id INTEGER,
 author_user_id INTEGER NOT NULL,
 claim_type TEXT NOT NULL,
 field_name TEXT,
 value_text TEXT,
 specification_kind TEXT,
 ownership_kind TEXT,
 body TEXT,
 target_claim_id INTEGER,
 occurred_at TEXT,
 status TEXT NOT NULL DEFAULT 'active',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(individual_id) REFERENCES individuals(id) ON DELETE CASCADE,
 FOREIGN KEY(observation_id) REFERENCES observations(id) ON DELETE SET NULL,
 FOREIGN KEY(author_user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(target_claim_id) REFERENCES claims(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS claim_responses (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 claim_id INTEGER NOT NULL,
 responder_user_id INTEGER NOT NULL,
 stance TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
 FOREIGN KEY(responder_user_id) REFERENCES users(id) ON DELETE CASCADE,
 UNIQUE(claim_id, responder_user_id)
);
CREATE TABLE IF NOT EXISTS claim_votes (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 claim_id INTEGER NOT NULL,
 user_id INTEGER NOT NULL,
 vote TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 UNIQUE(claim_id, user_id)
);

CREATE TABLE IF NOT EXISTS claim_spec_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 claim_id INTEGER NOT NULL,
 field_name TEXT NOT NULL,
 value_text TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS claim_listing_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 claim_id INTEGER NOT NULL,
 field_name TEXT NOT NULL,
 value_text TEXT NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
 UNIQUE(claim_id, field_name)
);

CREATE TABLE IF NOT EXISTS claim_identity_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 claim_id INTEGER NOT NULL,
 field_name TEXT NOT NULL,
 old_value TEXT,
 new_value TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS claim_evidence (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 claim_id INTEGER NOT NULL,
 media_asset_id INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE,
 FOREIGN KEY(media_asset_id) REFERENCES media_assets(id) ON DELETE CASCADE,
 UNIQUE(claim_id, media_asset_id)
);
CREATE TABLE IF NOT EXISTS crawl_listing_cache (
 source_site TEXT NOT NULL,
 source_listing_id TEXT NOT NULL,
 status TEXT NOT NULL,
 checked_at TEXT NOT NULL,
 recheck_after TEXT NOT NULL,
 PRIMARY KEY(source_site, source_listing_id)
);
CREATE INDEX IF NOT EXISTS idx_crawl_listing_cache_recheck_after
ON crawl_listing_cache(source_site, recheck_after);

CREATE TABLE IF NOT EXISTS crawl_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_site TEXT NOT NULL,
 started_at TEXT NOT NULL,
 finished_at TEXT,
 pages_discovered INTEGER DEFAULT 0,
 pages_fetched INTEGER DEFAULT 0,
 observations_created INTEGER DEFAULT 0,
 status TEXT NOT NULL,
 error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_observations_individual_id ON observations(individual_id);
CREATE INDEX IF NOT EXISTS idx_observations_source_url ON observations(source_url);

CREATE INDEX IF NOT EXISTS idx_user_guitars_user_id ON user_guitars(user_id);
CREATE INDEX IF NOT EXISTS idx_user_guitars_individual_id ON user_guitars(individual_id);

CREATE INDEX IF NOT EXISTS idx_claims_individual_id ON claims(individual_id);
CREATE INDEX IF NOT EXISTS idx_claims_observation_id ON claims(observation_id);
CREATE INDEX IF NOT EXISTS idx_claim_responses_claim_id ON claim_responses(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_votes_claim_id ON claim_votes(claim_id);

CREATE INDEX IF NOT EXISTS idx_media_assets_individual_id ON media_assets(individual_id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim_id ON claim_evidence(claim_id);

CREATE INDEX IF NOT EXISTS idx_claim_spec_items_claim_id ON claim_spec_items(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_listing_items_claim_id ON claim_listing_items(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_identity_items_claim_id ON claim_identity_items(claim_id);
