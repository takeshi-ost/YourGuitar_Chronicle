-- Equivalent to SQLite dispute locks; ordinary/admin paths must respect them.
CREATE FUNCTION ygc_guard_dispute_claim() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.claim_type IN ('ownership','listing','identity_correction') AND EXISTS
      (SELECT 1 FROM ownership_disputes WHERE individual_id=NEW.individual_id AND status='open') THEN
      RAISE EXCEPTION 'Ownership dispute lock: new ownership Claims are paused';
    END IF;
    RETURN NEW;
  END IF;
  IF (OLD.claim_type IN ('ownership','listing','identity_correction') AND EXISTS
      (SELECT 1 FROM ownership_disputes WHERE individual_id=OLD.individual_id AND status='open'))
    OR EXISTS (SELECT 1 FROM ownership_dispute_claims dc JOIN ownership_disputes d ON d.id=dc.dispute_id
      WHERE dc.claim_id=OLD.id AND d.status NOT IN ('resolving','checking')) THEN
    RAISE EXCEPTION 'Ownership dispute lock: use dispute reconsideration';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER dispute_claim_guard BEFORE INSERT OR UPDATE OR DELETE ON claims
FOR EACH ROW EXECUTE FUNCTION ygc_guard_dispute_claim();
CREATE FUNCTION ygc_guard_dispute_individual() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF EXISTS (SELECT 1 FROM ownership_disputes WHERE individual_id=OLD.id) THEN
      RAISE EXCEPTION 'Ownership dispute lock: retain the dispute history';
    END IF;
    RETURN OLD;
  END IF;
  IF EXISTS (SELECT 1 FROM ownership_disputes WHERE individual_id=OLD.id AND status='open'
      AND NEW.current_owner_user_id IS DISTINCT FROM locked_owner_id) THEN
    RAISE EXCEPTION 'Ownership dispute lock: Current Owner is frozen';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER dispute_owner_update BEFORE UPDATE OF current_owner_user_id ON individuals
FOR EACH ROW EXECUTE FUNCTION ygc_guard_dispute_individual();
CREATE TRIGGER dispute_individual_delete BEFORE DELETE ON individuals
FOR EACH ROW EXECUTE FUNCTION ygc_guard_dispute_individual();
