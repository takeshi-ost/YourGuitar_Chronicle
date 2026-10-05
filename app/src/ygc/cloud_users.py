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
                row=con.execute(f'SELECT {COLUMNS} FROM account_records WHERE id=%s',(individual_id,)).fetchone()
                if row is None:raise UserMissing()
                return dict(row)
