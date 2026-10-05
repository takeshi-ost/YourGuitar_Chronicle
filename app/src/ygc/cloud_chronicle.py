"""Bounded Admin-only Claim history without private evidence or mutations."""
from ygc.db.postgres import connect
from ygc.cloud_guitars import MAX_ID,GuitarMissing

LISTING_FIELDS=('manufacturer','model','serial_number','finish','year','listing_title','listing_date',
                'location_country','location_region','owner_name','owner_type','source_site','source_listing_id')


def read(settings,operations,actor,individual_id,*,after=0,limit=25):
    if type(individual_id) is not int or not 0<individual_id<=MAX_ID or type(after) is not int or not 0<=after<=MAX_ID or type(limit) is not int or not 1<=limit<=50:
        raise ValueError('Invalid Chronicle page.')
    with operations.access('admin_read',actor):
        with connect(settings,'chronicle') as con:
            con.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            con.execute("SET LOCAL statement_timeout='5s'")
            con.execute("SET LOCAL lock_timeout='2s'")
            if not con.execute('SELECT 1 FROM individuals WHERE id=%s',(individual_id,)).fetchone():raise GuitarMissing()
            total=con.execute('SELECT COUNT(*) AS total FROM claims WHERE individual_id=%s',(individual_id,)).fetchone()['total']
            rows=con.execute('''SELECT c.id,c.author_user_id,u.display_name AS author_name,c.claim_type,
              c.field_name,left(c.value_text,2000) AS value_text,left(c.body,2000) AS body,c.ownership_kind,
              c.occurred_at,c.created_at,c.status,c.verification_status,
              CASE WHEN u.ban_status='normal' THEN c.status ELSE 'inactive' END AS effective_status
              FROM claims c JOIN users u ON u.id=c.author_user_id
              WHERE c.individual_id=%s AND (%s=0 OR c.id<%s) ORDER BY c.id DESC LIMIT %s''',
              (individual_id,after,after,limit+1)).fetchall()
            more=len(rows)>limit;rows=[dict(row) for row in rows[:limit]]
            ids=[row['id'] for row in rows]
            items={key:[] for key in ids}
            if ids:
                # Structured Listing fields are fixed; URLs, images and Evidence payloads are excluded.
                listing=con.execute('''SELECT claim_id,field_name,left(value_text,1000) AS value_text
                  FROM claim_listing_items WHERE claim_id=ANY(%s) AND field_name=ANY(%s)
                  ORDER BY claim_id,field_name''',(ids,list(LISTING_FIELDS))).fetchall()
                for item in listing:items[item['claim_id']].append(dict(field_name=item['field_name'],value_text=item['value_text']))
                # Custom Specification names are content; retain at most 20 items per Claim.
                specs=con.execute('''SELECT claim_id,left(field_name,120) AS field_name,left(value_text,1000) AS value_text
                  FROM (SELECT *,row_number() OVER(PARTITION BY claim_id ORDER BY id) AS n
                        FROM claim_spec_items WHERE claim_id=ANY(%s)) AS bounded WHERE n<=20 ORDER BY claim_id,n''',(ids,)).fetchall()
                for item in specs:items[item['claim_id']].append(dict(field_name=item['field_name'],value_text=item['value_text']))
            for row in rows:row['items']=items[row['id']]
            return dict(items=rows,total=total,next_after=rows[-1]['id'] if more else None)
