-- Projection receipt and identity protection; signature guitar remains content.
CREATE UNIQUE INDEX participant_uuid ON users(app_user_id);
CREATE TABLE account_projection_receipts (
 account_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 app_user_id TEXT NOT NULL UNIQUE,
 revision BIGINT NOT NULL CHECK(revision>0),
 applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE FUNCTION ygc_guard_participant_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id OR
    (OLD.app_user_id IS NOT NULL AND NEW.app_user_id IS DISTINCT FROM OLD.app_user_id) THEN
  RAISE EXCEPTION 'Participant identity is immutable';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER immutable_participant_identity BEFORE UPDATE OF id,app_user_id ON users
 FOR EACH ROW EXECUTE FUNCTION ygc_guard_participant_identity();
