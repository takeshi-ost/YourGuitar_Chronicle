-- Preserve identity reservations independently of content recovery.
CREATE FUNCTION ygc_guard_account_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Disable accounts instead of deleting their identity registry';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.app_user_id IS DISTINCT FROM OLD.app_user_id THEN
    RAISE EXCEPTION 'Account identity is immutable';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER immutable_account_identity BEFORE UPDATE OR DELETE ON account_records
FOR EACH ROW EXECUTE FUNCTION ygc_guard_account_identity();
