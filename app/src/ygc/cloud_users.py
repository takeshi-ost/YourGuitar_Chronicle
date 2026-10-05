"""Read-only canonical Accounts records for the administrator console."""
from ygc.db.postgres import connect

FIELDS = ('id','app_user_id','display_name','account_type','role','disabled','ban_status',
          'location_country','location_region','bio','created_at','updated_at')
COLUMNS = ','.join(FIELDS)
MAX_ID = 2**63-1


def positive_id(value):
    if not isinstance(value,str) or not value.isascii() or not value.isdecimal():
        raise ValueError('Invalid identifier.')
    number=int(value)
    if not 0 < number <= MAX_ID:raise ValueError('Invalid identifier.')
    return number


def parameters(query):
    if set(query)-{'q','after','limit'} or any(len(query.getlist(k))!=1 for k in query):
        raise ValueError('Unknown or repeated query parameter.')
    q=query.get('q','').strip()
    if len(q)>120 or any(ord(c)<32 for c in q):raise ValueError('Invalid search.')
    after=positive_id(query['after']) if 'after' in query else 0
    limit=positive_id(query['limit']) if 'limit' in query else 25
    if limit>50:raise ValueError('Page size exceeded.')
    return q,after,limit


class UserMissing(LookupError):pass


class CloudUsers:
    def __init__(self,settings,operations):self.settings,self.operations=settings,operations

    def list(self,actor,*,q='',after=0,limit=25):
        if not isinstance(q,str) or len(q)>120 or type(after)!=int or not 0<=after<=MAX_ID or type(limit)!=int or not 1<=limit<=50:
            raise ValueError('Invalid page.')
        with self.operations.access('admin_read',actor):
            with connect(self.settings,'accounts') as con:
                con.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                con.execute("SET LOCAL statement_timeout='5s'")
                con.execute("SET LOCAL lock_timeout='2s'")
                escaped=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
                pattern='%'+escaped+'%'
                rows=con.execute(f'''SELECT {COLUMNS} FROM account_records WHERE id>%s
                    AND (display_name ILIKE %s OR app_user_id ILIKE %s OR id::text ILIKE %s)
                    ORDER BY id LIMIT %s''',(after,pattern,pattern,pattern,limit+1)).fetchall()
                total=con.execute('SELECT COUNT(*) AS total FROM account_records').fetchone()['total']
                more=len(rows)>limit;rows=rows[:limit]
                return {'total':total,'items':[dict(row) for row in rows], 'next_after':rows[-1]['id'] if more else None}

    def detail(self,actor,individual_id):
        if type(individual_id)!=int or not 0<individual_id<=MAX_ID:raise ValueError('Invalid identifier.')
        with self.operations.access('admin_read',actor):
            with connect(self.settings,'accounts') as con:
                con.execute('SET TRANSACTION READ ONLY')
                con.execute("SET LOCAL statement_timeout='5s'")
                con.execute("SET LOCAL lock_timeout='2s'")
                row=con.execute(f'SELECT {COLUMNS},projection_version FROM account_records WHERE id=%s',(individual_id,)).fetchone()
                if row is None:raise UserMissing()
                result=dict(row);result['profile_revision']=str(result.pop('projection_version'));return result

    def guitars(self,actor,user_id,*,kind,after=0,limit=25):
        from ygc.owned_guitar_visibility import VISIBLE_SQL
        if kind not in ('owned','formerly_owned') or type(user_id) is not int or not 0<user_id<=MAX_ID or type(after) is not int or not 0<=after<=MAX_ID or type(limit) is not int or not 1<=limit<=50:
            raise ValueError('Invalid ownership page.')
        with self.operations.access('admin_read',actor):
            with connect(self.settings,'accounts') as source:
                source.execute('SET TRANSACTION READ ONLY')
                source.execute("SET LOCAL statement_timeout='5s'")
                user=source.execute('SELECT app_user_id FROM account_records WHERE id=%s',(user_id,)).fetchone()
                if not user:raise UserMissing()
                with connect(self.settings,'chronicle') as con:
                    con.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    con.execute("SET LOCAL statement_timeout='5s'")
                    con.execute("SET LOCAL lock_timeout='2s'")
                    if kind=='owned':
                        where='i.current_owner_user_id=%s'
                        table='individuals i JOIN users u ON u.id=i.current_owner_user_id'
                    else:
                        table='user_guitars ug JOIN individuals i ON i.id=ug.individual_id JOIN users u ON u.id=ug.user_id'
                        where="ug.user_id=%s AND ug.ownership_status='former_owner' AND "+VISIBLE_SQL
                    scope=f"{where} AND u.app_user_id=%s"
                    params=(user_id,user['app_user_id'])
                    total=con.execute(f'SELECT COUNT(*) AS total FROM {table} WHERE {scope}',params).fetchone()['total']
                    rows=con.execute(f'SELECT i.id,i.manufacturer,i.model,i.year,i.serial_number FROM {table} WHERE {scope} AND i.id>%s ORDER BY i.id LIMIT %s',params+(after,limit+1)).fetchall()
                    more=len(rows)>limit;rows=[dict(row) for row in rows[:limit]]
                    return dict(items=rows,total=total,next_after=rows[-1]['id'] if more else None)

    def edit_profile(self,actor,user_id,body):
        import json,uuid
        from ygc.cloud_profile import validate,ProfileConflict
        from ygc.db.postgres_accounts import now
        if type(user_id) is not int or not 0<user_id<=MAX_ID:raise ValueError('Invalid identifier.')
        version,fields=validate(body)
        with connect(self.settings,'operations') as guard:
            if not guard.execute('SELECT pg_try_advisory_xact_lock(79432190) AS locked').fetchone()['locked']:
                raise ProfileConflict('Database maintenance or Crawl is running.')
            with self.operations.account_access('admin_write',actor) as (con,mode,account):
                con.execute("SET LOCAL lock_timeout='2s'")
                con.execute("SET LOCAL statement_timeout='5s'")
                target=con.execute('SELECT * FROM account_records WHERE id=%s FOR UPDATE',(user_id,)).fetchone()
                if not target:raise UserMissing()
                if target['projection_version']!=version:raise ProfileConflict('Profile changed; reload before editing.')
                timestamp=now()
                result=con.execute('''UPDATE account_records SET display_name=%s,location_country=%s,location_region=%s,bio=%s,updated_at=%s
                    WHERE id=%s RETURNING projection_version''',(*fields.values(),timestamp,user_id)).fetchone()
                changed=[key for key,value in fields.items() if target[key]!=value]
                con.execute('INSERT INTO account_metadata(key,value) VALUES(%s,%s)',
                    ('admin_profile:'+str(uuid.uuid4()),json.dumps(dict(action='admin_profile_edit',actor_app_user_id=account['app_user_id'],
                      target_app_user_id=target['app_user_id'],changed_fields=changed,previous_revision=version,
                      revision=result['projection_version'],occurred_at=timestamp))))
            # Account commit and outbox enqueue precede releasing the service-mode fence.
            # The existing projection Job handles Chronicle updates and retry after failures.
            return dict(id=str(user_id),profile_revision=str(result['projection_version']),saved=True)
