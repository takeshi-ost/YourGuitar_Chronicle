"""Opaque compare-and-swap token for a Claim decision."""
import hashlib
import json
FIELDS=('id','individual_id','status','verification_status','admin_verification','updated_at')
class ClaimConflict(ValueError):pass

def revision(row):
    return hashlib.sha256(json.dumps([row[k] for k in FIELDS],default=str,separators=(',',':')).encode()).hexdigest()
