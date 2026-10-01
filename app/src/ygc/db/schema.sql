PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS crawl_unregistered_records (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_site TEXT NOT NULL,
 source_listing_id TEXT NOT NULL,
 source_url TEXT NOT NULL,
 observed_at TEXT NOT NULL,
 reason TEXT NOT NULL,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 created_at TEXT NOT NULL,
 UNIQUE(source_site, source_listing_id)
);
-- Full legacy rows, including extraction data and provenance. No expiry or
-- cascading foreign key: preserved records must survive legacy row removal.
CREATE TABLE IF NOT EXISTS legacy_crawl_archive (
 legacy_observation_id INTEGER PRIMARY KEY,
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 payload_sha256 TEXT NOT NULL,
 archived_at TEXT NOT NULL
);
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
 ban_status TEXT NOT NULL DEFAULT 'normal' CHECK (ban_status IN ('normal','silent_ban','ban')),
 identity_provider TEXT,
 identity_subject TEXT,
 location_country TEXT,
 location_region TEXT,
 bio TEXT,
 date_of_birth TEXT,
 avatar_storage_path TEXT,
 avatar_original_filename TEXT,
 avatar_mime_type TEXT,
 birth_visibility TEXT NOT NULL DEFAULT 'Private',
 residence_visibility TEXT NOT NULL DEFAULT 'Private',
 bio_visibility TEXT NOT NULL DEFAULT 'Public',
 avatar_visibility TEXT NOT NULL DEFAULT 'Public',
 signature_individual_id INTEGER,
 theme TEXT NOT NULL DEFAULT 'dark_default',
 theme_override TEXT,
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
CREATE TABLE IF NOT EXISTS user_favorites (
 user_id INTEGER NOT NULL,
 individual_id INTEGER NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(user_id, individual_id),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(individual_id) REFERENCES individuals(id) ON DELETE CASCADE
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
 ownership_source TEXT,
 ownership_pair_id TEXT,
 previous_owner_text TEXT,
 body TEXT,
 target_claim_id INTEGER,
 occurred_at TEXT,
 status TEXT NOT NULL DEFAULT 'active',
 verification_status TEXT NOT NULL DEFAULT 'positive',
 admin_verification INTEGER NOT NULL DEFAULT 0,
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
-- Structured source evidence belongs to a Claim. The existing observations
-- table remains available for crawl checkpoints and legacy reads during migration.
CREATE TABLE IF NOT EXISTS claim_source_evidence (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
 evidence_type TEXT NOT NULL CHECK (evidence_type IN ('marketplace_listing', 'acquisition_date')),
 source_site TEXT,
 source_listing_id TEXT,
 source_url TEXT,
 captured_at TEXT,
 effective_date TEXT,
 date_basis TEXT,
 payload_json TEXT,
 legacy_observation_id INTEGER UNIQUE,
 created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_source_listing_unique
 ON claim_source_evidence(source_site, source_listing_id)
 WHERE source_site IS NOT NULL AND source_listing_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_claim_source_evidence_claim
 ON claim_source_evidence(claim_id);
CREATE TABLE IF NOT EXISTS claim_specification_source (
 claim_id INTEGER PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
 source_site TEXT NOT NULL,
 source_listing_id TEXT NOT NULL,
 source_url TEXT,
 captured_at TEXT NOT NULL,
 extracted_json TEXT NOT NULL,
 UNIQUE(source_site, source_listing_id, claim_id)
);
CREATE TABLE IF NOT EXISTS notifications (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 recipient_user_id INTEGER NOT NULL,
 actor_user_id INTEGER,
 notification_type TEXT NOT NULL,
 individual_id INTEGER,
 claim_id INTEGER,
 title TEXT NOT NULL,
 body TEXT,
 is_read INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,
 read_at TEXT,
 FOREIGN KEY(recipient_user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
 FOREIGN KEY(individual_id) REFERENCES individuals(id) ON DELETE CASCADE,
 FOREIGN KEY(claim_id) REFERENCES claims(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_notifications_recipient_read_created
ON notifications(recipient_user_id, is_read, created_at DESC);

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

CREATE TABLE IF NOT EXISTS crawl_candidates (
 source_site TEXT NOT NULL,
 source_listing_id TEXT NOT NULL,
 claim_json TEXT NOT NULL,
 provenance_json TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 reason TEXT,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(source_site, source_listing_id)
);
CREATE TABLE IF NOT EXISTS crawl_detail_cache (
 source_site TEXT NOT NULL,
 source_listing_id TEXT NOT NULL,
 payload_json TEXT NOT NULL,
 fetched_at TEXT NOT NULL,
 PRIMARY KEY(source_site, source_listing_id)
);
CREATE INDEX IF NOT EXISTS idx_crawl_candidates_status
ON crawl_candidates(source_site, status);

CREATE TABLE IF NOT EXISTS crawl_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_site TEXT NOT NULL,
 started_at TEXT NOT NULL,
 finished_at TEXT,
 pages_discovered INTEGER DEFAULT 0,
 pages_fetched INTEGER DEFAULT 0,
 observations_created INTEGER DEFAULT 0,
 status TEXT NOT NULL,
 error_message TEXT,
 category TEXT,
 year_min INTEGER,
 year_max INTEGER,
 phase TEXT,
 counts_json TEXT,
 updated_at TEXT
);
CREATE TABLE IF NOT EXISTS crawl_programs (
 source_site TEXT NOT NULL,
 category TEXT NOT NULL,
 year_min INTEGER NOT NULL,
 year_max INTEGER NOT NULL,
 page_url TEXT,
 pending_json TEXT,
 next_url TEXT,
 processed INTEGER NOT NULL DEFAULT 0,
 observations_created INTEGER NOT NULL DEFAULT 0,
 finished INTEGER NOT NULL DEFAULT 0,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(source_site, category, year_min, year_max)
);
CREATE TABLE IF NOT EXISTS crawl_listing_checks (
 source_site TEXT NOT NULL,
 source_listing_id TEXT NOT NULL,
 api_url TEXT,
 checked_at TEXT,
 missing_since TEXT,
 status TEXT NOT NULL DEFAULT 'unknown',
 PRIMARY KEY(source_site, source_listing_id)
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

CREATE TABLE IF NOT EXISTS claim_admin_actions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 claim_id INTEGER NOT NULL,
 individual_id INTEGER NOT NULL,
 action TEXT NOT NULL,
 previous_verification TEXT,
 actor TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_admin_actions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 previous_ban_status TEXT NOT NULL,
 ban_status TEXT NOT NULL,
 created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS individual_resolution_actions (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 source_id INTEGER NOT NULL,
 keep_id INTEGER NOT NULL,
 action TEXT NOT NULL,
 created_at TEXT NOT NULL
);

-- Social relationships never participate in Claim/Observation evaluation.
CREATE TABLE IF NOT EXISTS user_follows (
 follower_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 followed_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 created_at TEXT NOT NULL,
 PRIMARY KEY (follower_user_id, followed_user_id),
 CHECK (follower_user_id <> followed_user_id)
);
CREATE INDEX IF NOT EXISTS idx_user_follows_followed ON user_follows(followed_user_id, follower_user_id);

-- Private social messages, entirely independent of Claims and Evidence.
CREATE TABLE IF NOT EXISTS direct_messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 sender_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 recipient_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 2000),
 created_at TEXT NOT NULL,
 read_at TEXT,
 CHECK(sender_user_id <> recipient_user_id)
);
CREATE INDEX IF NOT EXISTS idx_dm_recipient_read ON direct_messages(recipient_user_id,read_at,id);
CREATE INDEX IF NOT EXISTS idx_dm_sender_recipient ON direct_messages(sender_user_id,recipient_user_id,id);

CREATE TABLE IF NOT EXISTS claim_transfers (
 claim_id INTEGER PRIMARY KEY REFERENCES claims(id) ON DELETE CASCADE,
 from_user_id INTEGER NOT NULL,
 to_user_id INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','accepted','declined','cancelled')),
 created_at TEXT NOT NULL,
 resolved_at TEXT,
 CHECK(from_user_id<>to_user_id)
);
CREATE INDEX IF NOT EXISTS idx_claim_transfers_to_state ON claim_transfers(to_user_id,state);
CREATE TABLE IF NOT EXISTS claim_transfer_acceptance (
 claim_id INTEGER PRIMARY KEY REFERENCES claim_transfers(claim_id) ON DELETE CASCADE,
 accepted_by_user_id INTEGER NOT NULL,
 accepted_at TEXT NOT NULL,
 current_owner_user_id INTEGER NOT NULL
);

-- Private Acquire application and durable review Evidence, separate from experiment jobs.
CREATE TABLE IF NOT EXISTS acquire_applications (
 request_kind TEXT NOT NULL DEFAULT 'acquire', listing_payload TEXT,
 revision TEXT PRIMARY KEY,
 applicant_id INTEGER NOT NULL,
 individual_id INTEGER REFERENCES individuals(id) ON DELETE SET NULL,
 original_individual_id INTEGER NOT NULL,
 serial TEXT NOT NULL, challenge TEXT NOT NULL,
 expires_at REAL NOT NULL, created_at TEXT NOT NULL,
 submitted_at TEXT, started_at TEXT, completed_at TEXT,
 acquisition_date TEXT, body TEXT,
 status TEXT NOT NULL DEFAULT 'draft',
 images TEXT, image_meta TEXT, reference_source TEXT,
 product_details TEXT, product_observations TEXT,
 attempts INTEGER NOT NULL DEFAULT 0,
 lease_token TEXT, lease_until REAL,
 error TEXT, received TEXT, result TEXT, report TEXT,
 prompt_version TEXT NOT NULL,
 claim_id INTEGER UNIQUE REFERENCES claims(id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_acquire_open_application
 ON acquire_applications(applicant_id,individual_id)
 WHERE status IN ('draft','pending','processing','error');
CREATE TABLE IF NOT EXISTS acquire_application_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 revision TEXT NOT NULL REFERENCES acquire_applications(revision),
 at TEXT NOT NULL, kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
);
