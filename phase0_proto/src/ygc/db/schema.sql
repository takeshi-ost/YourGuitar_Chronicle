PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS individuals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 manufacturer TEXT NOT NULL,
 model TEXT,
 finish TEXT,
 year TEXT,
 serial_number TEXT,
 normalized_manufacturer TEXT NOT NULL,
 normalized_model TEXT,
 normalized_serial TEXT,
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
 seller TEXT,
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
