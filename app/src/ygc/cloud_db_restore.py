"""Known-schema data restoration; retain canonical identities and current authority."""
from collections import defaultdict
from datetime import datetime, timezone
import gzip
from io import BytesIO
import json
from psycopg import sql
from ygc.cloud_db_snapshot import verify_snapshot,decode_cell,TYPED_COLUMNS
from ygc.db.postgres import recorded_schema,validate_schema
from ygc.db.postgres_accounts import PostgresAccounts,PROFILE_FIELDS
from ygc.cloud_backup_preflight import MAX_RESTORE_RAW,BackupCapacityError


def load(data,target,sha):
    verify_snapshot(data,target,sha)
    rows=defaultdict(list);sequences=[];total=0
    with gzip.GzipFile(fileobj=BytesIO(data)) as source:
        first=source.readline();total=len(first);header=json.loads(first)
        if total>MAX_RESTORE_RAW:raise BackupCapacityError('restore_staging_limit','restore_capacity')
        for raw in source:
            total+=len(raw)
            if total>MAX_RESTORE_RAW:raise BackupCapacityError('restore_staging_limit','restore_capacity')
            row=json.loads(raw)
            if 'table' in row:
                table=row['table']
                rows[table].append({column:decode_cell(value,TYPED_COLUMNS.get((target,table,column))) for column,value in zip(header['tables'][table],row['values'])})
            elif 'sequences' in row:sequences=row['sequences']
    for table in header['tables']:rows.setdefault(table,[])
    return header,rows,sequences


def verify_restored_dispute_originals(storage,rows):
    """Require every attached original, including exact immutable generations.

    Text-only evidence has no MIME or original. Legacy BYTEA remains readable;
    a v3 cloud attachment has MIME plus one reference and no inline content.
    Errors never include object names, filenames, evidence text or identifiers.
    """
    evidence=[]
    for row in rows.get('ownership_dispute_evidence',[]):
        content=row['content']
        if content is not None and not isinstance(content,(bytes,memoryview)):
            raise ValueError('Invalid legacy dispute original.')
        evidence.append({'id':row['id'],'content_type':row['content_type'],
            'content_size':None if content is None else len(content)})
    verify_dispute_originals(storage,rows.get('ownership_dispute_originals',[]),evidence)


def verify_dispute_originals(storage,original_rows,evidence_rows):
    """Shared bounded-metadata validation for restore and streaming verification."""
    from ygc.cloud_dispute_storage import verify_original
    originals={}
    objects=set()
    for row in original_rows:
        if row['evidence_id'] in originals:raise ValueError('Duplicate dispute original reference.')
        identity=(row['object_scope'],row['object_name'],row['object_generation'])
        if identity in objects:raise ValueError('Duplicate dispute original object.')
        objects.add(identity)
        originals[row['evidence_id']]=row
    identities=set()
    for evidence in evidence_rows:
        identity=evidence['id']
        if identity in identities:raise ValueError('Duplicate dispute evidence identity.')
        identities.add(identity)
        original=originals.pop(identity,None)
        size=evidence['content_size'];mime=evidence['content_type']
        if original is not None:
            if size is not None or mime!=original['content_type']:
                raise ValueError('Dispute original metadata differs.')
            if storage is None:raise ValueError('Dispute original storage verification required.')
            verify_original(storage,original)
        elif size is not None:
            if type(size) is not int or not 0<size<=12*1024*1024 or mime not in ('application/pdf','image/jpeg'):
                raise ValueError('Invalid legacy dispute original.')
        elif mime is not None:
            raise ValueError('Dispute original reference missing.')
    if originals:raise ValueError('Dispute original evidence missing.')


def content_restore_schema(header,revision):
    """One explicit additive compatibility bridge, never a generic relaxation."""
    target=header['target']
    saved=recorded_schema(target,{'version':header['schema_version'],'checksum':header['schema_checksum']})
    current=recorded_schema(target,revision)
    if header['tables']!=saved['tables']:raise ValueError('Wrong schema columns.')
    if (revision['version'],revision['checksum'])==(header['schema_version'],header['schema_checksum']):
        return current
    if target!='chronicle' or (header['schema_version'],revision['version']) not in ((1,3),(2,3)):
        raise ValueError('Restore schema differs.')
    additions={'ownership_dispute_originals'}
    if header['schema_version']==1:additions.add('account_projection_receipts')
    if set(current['tables'])-set(saved['tables'])!=additions or any(current['tables'].get(table)!=columns for table,columns in saved['tables'].items()):
        raise ValueError('Restore schema differs.')
    return current


def order(con,tables):
    deps={table:set() for table in tables};self_columns=defaultdict(list)
    for row in con.execute("""SELECT c.relname AS child,p.relname AS parent,a.attname AS field
      FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_class p ON p.oid=k.confrelid
      JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=ANY(k.conkey)
      WHERE k.contype='f' AND n.nspname='public'"""):
        if row['child'] not in deps:continue
        if row['parent']==row['child']:self_columns[row['child']].append(row['field'])
        elif row['parent'] in deps:deps[row['child']].add(row['parent'])
    result=[]
    while deps:
        ready=sorted(t for t,parents in deps.items() if not parents)
        if not ready:raise ValueError('Cyclic table dependencies.')
        result.extend(ready)
        for table in ready:del deps[table]
        for parents in deps.values():parents.difference_update(ready)
    return result,self_columns


def self_order(rows,fields):
    if not fields:return rows
    pending={row['id']:row for row in rows};done=set();result=[]
    if len(pending)!=len(rows):raise ValueError('Duplicate row identity.')
    while pending:
        ready=[key for key,row in pending.items() if all(row.get(field) is None or row[field]==key or row[field] in done for field in fields)]
        if not ready:raise ValueError('Unresolved self reference.')
        for key in ready:result.append(pending.pop(key));done.add(key)
    return result


def sequence_state(con):
    return {row['sequencename']:dict(con.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier(row['sequencename']))).fetchone()) for row in con.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public'").fetchall()}


def advance_sequences(con,before,saved):
    supplied={row['name']:row for row in saved}
    if set(supplied)!=set(before):raise ValueError('Sequence schema differs.')
    for row in con.execute("""SELECT c.relname AS table_name,a.attname AS column_name,s.relname AS sequence_name
      FROM pg_class s JOIN pg_depend d ON d.objid=s.oid AND d.deptype IN ('a','i')
      JOIN pg_class c ON c.oid=d.refobjid JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=d.refobjsubid
      JOIN pg_namespace n ON n.oid=s.relnamespace WHERE s.relkind='S' AND n.nspname='public'"""):
        name=row['sequence_name']
        maximum=con.execute(sql.SQL('SELECT COALESCE(MAX({}),0) AS maximum FROM {}').format(sql.Identifier(row['column_name']),sql.Identifier(row['table_name']))).fetchone()['maximum']
        # Reservations never move backwards, including after failed transactions.
        latest=con.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier(name))).fetchone()
        bound=max(before[name]['last_value'],supplied[name]['last_value'],maximum,1)
        gap=max(0,bound-latest['last_value'])+(0 if latest['is_called'] else 1)
        if gap>100000:raise ValueError('Sequence advance exceeds staging limit.')
        # USAGE permits nextval; runtime has no UPDATE/setval privilege.
        if gap:con.execute('SELECT nextval(%s) FROM generate_series(1,%s)',(name,gap)).fetchall()


def insert(con,table,columns,rows):
    if not rows:return
    statement=sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,columns)),sql.SQL(',').join(sql.Placeholder() for _ in columns))
    with con.cursor() as cursor:
        cursor.executemany(statement,[tuple(row[column] for column in columns) for row in rows])


def check_users(rows,current):
    registry={row['id']:row['app_user_id'] for row in current}
    if any(registry.get(row['id'])!=row['app_user_id'] for row in rows):raise ValueError('Content identities do not match the current registry.')


def replace_content(con,header,rows,sequences,current,*,storage=None):
    revision=con.execute('SELECT version,checksum FROM ygc_schema_version WHERE id=1').fetchone()
    expected=content_restore_schema(header,revision)
    validate_schema(con,expected)
    # Only recognized old archives receive empty additive tables. The header and
    # its checksum stay unchanged, and saved column lists remain authoritative.
    if set(rows)!=set(header['tables']):raise ValueError('Restore table data differs.')
    rows={**rows,**{table:[] for table in set(expected['tables'])-set(header['tables'])}}
    if header['target']=='chronicle':verify_restored_dispute_originals(storage,rows)
    tables=list(expected['tables']);ordered,self_refs=order(con,tables)
    con.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(sql.SQL(',').join(map(sql.Identifier,tables))))
    before=sequence_state(con)
    if header['target']=='chronicle':check_users(rows['users'],current)
    for table in reversed(ordered):con.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(table)))
    for table in ordered:insert(con,table,expected['tables'][table],self_order(rows[table],self_refs[table]))
    if header['target']=='chronicle':
        # A saved lease never authorizes a callback against restored state.
        con.execute("UPDATE acquire_applications SET status=CASE WHEN status='processing' THEN 'pending' ELSE status END,lease_token=NULL,lease_until=NULL")
        accounts=PostgresAccounts(None)
        for account in current:accounts._apply_projection(con,account,force_rebuild=True)
    advance_sequences(con,before,sequences)


def restore_accounts(con,header,rows,sequences):
    """Profiles/social data rewind; newer accounts, links, security and consent survive."""
    revision=con.execute('SELECT version,checksum FROM ygc_schema_version WHERE id=1').fetchone()
    if revision['version']!=header['schema_version'] or revision['checksum']!=header['schema_checksum']:raise ValueError('Restore schema differs.')
    validate_schema(con,recorded_schema('accounts',revision))
    current={row['id']:dict(row) for row in con.execute('SELECT * FROM account_records')}
    check_users(rows['account_records'],list(current.values()))
    links={(row['issuer'],row['tenant'],row['subject']):row['app_user_id'] for row in con.execute('SELECT * FROM identity_links')}
    if any(links.get((row['issuer'],row['tenant'],row['subject']))!=row['app_user_id'] for row in rows['identity_links']):raise ValueError('Identity links require explicit mapping.')
    before=sequence_state(con)
    for row in rows['account_records']:
        fields=sorted(PROFILE_FIELDS|{'account_type'})
        con.execute(sql.SQL('UPDATE account_records SET {},updated_at=%s WHERE id=%s').format(sql.SQL(',').join(sql.SQL('{}=%s').format(sql.Identifier(field)) for field in fields)),
                    (*[row[field] for field in fields],datetime.now(timezone.utc).isoformat(),row['id']))
    for table in ('account_direct_messages','account_user_follows'):
        con.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(table)))
        insert(con,table,header['tables'][table],rows[table])
    # Local dummy sessions are never resurrected; Google sessions are managed by Google.
    con.execute('DELETE FROM local_sessions')
    advance_sequences(con,before,sequences)
