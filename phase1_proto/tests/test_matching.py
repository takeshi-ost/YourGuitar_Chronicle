from ygc.db.repository import Repository,utcnow
from ygc.matching.individual_matcher import match_or_create
def test_same_key_maps_to_one_individual(tmp_path):
    r=Repository(tmp_path/'t.db'); r.init_db(); a=match_or_create(r,'Fender','Telecaster Thinline','729321'); b=match_or_create(r,'FENDER',' telecaster  thinline ','729 321'); assert a==b
    base={'individual_id':a,'manufacturer':'Fender','model':'Telecaster Thinline','serial_number':'729321','seller':'Shop A','source_site':'reverb','source_url':'https://example.test/a','source_listing_id':'a','observed_at':utcnow(),'listing_date':None,'title':'A','raw_text':'Serial 729321','serial_confidence':0.95,'extraction_version':'test','created_at':utcnow()}
    r.upsert_observation(base); r.upsert_observation(dict(base,source_url='https://example.test/b',source_listing_id='b',seller='Shop B')); _,obs=r.get_individual(a); assert len(obs)==2
