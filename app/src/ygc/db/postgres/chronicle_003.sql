-- Additive private dispute originals. Existing BYTEA evidence is untouched.
-- Objects are immutable fixed generations in the existing private content
-- bucket. Removing a database reference never removes the underlying object.
CREATE TABLE ownership_dispute_originals (
 evidence_id BIGINT PRIMARY KEY REFERENCES ownership_dispute_evidence(id),
 object_scope TEXT NOT NULL CHECK(object_scope='content'),
 object_name TEXT NOT NULL CHECK(object_name ~ '^media/[0-9a-f]{32}$'),
 object_generation BIGINT NOT NULL CHECK(object_generation>0),
 byte_size BIGINT NOT NULL CHECK(byte_size>0 AND byte_size<=12582912),
 content_type TEXT NOT NULL CHECK(content_type IN ('application/pdf','image/jpeg')),
 sha256 TEXT NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
 created_at TEXT NOT NULL CHECK(length(created_at)>0),
 UNIQUE(object_scope,object_name,object_generation)
);

CREATE FUNCTION ygc_guard_dispute_original() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
  RAISE EXCEPTION 'Private original metadata is immutable';
 END IF;
 -- Lock the evidence row, including for administrative imports, so an
 -- overlapping metadata mutation cannot race this consistency check.
 PERFORM 1 FROM ownership_dispute_evidence e WHERE e.id=NEW.evidence_id
  AND e.content IS NULL AND e.content_type=NEW.content_type FOR UPDATE;
 IF NOT FOUND THEN
  RAISE EXCEPTION 'Private original metadata does not match its evidence';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_dispute_original BEFORE INSERT OR UPDATE ON ownership_dispute_originals
 FOR EACH ROW EXECUTE FUNCTION ygc_guard_dispute_original();

CREATE FUNCTION ygc_guard_dispute_evidence_original() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS (SELECT 1 FROM ownership_dispute_originals WHERE evidence_id=OLD.id) AND
    (NEW.id IS DISTINCT FROM OLD.id OR NEW.dispute_id IS DISTINCT FROM OLD.dispute_id OR
     NEW.claim_id IS DISTINCT FROM OLD.claim_id OR NEW.author_id IS DISTINCT FROM OLD.author_id OR
     NEW.content IS DISTINCT FROM OLD.content OR
     NEW.content_type IS DISTINCT FROM OLD.content_type) THEN
  RAISE EXCEPTION 'Externally stored private original evidence is immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_dispute_evidence_original BEFORE UPDATE OF id,dispute_id,claim_id,author_id,content,content_type
 ON ownership_dispute_evidence FOR EACH ROW EXECUTE FUNCTION ygc_guard_dispute_evidence_original();
