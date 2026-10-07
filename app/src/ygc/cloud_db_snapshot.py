"""Bounded, versioned logical snapshots, never executable SQL or a restore API."""
from datetime import datetime,timezone
import base64
import math
import gzip
import hashlib
import json
from io import BytesIO
from ygc.db.postgres import connect,recorded_schema,validate_schema,TARGETS
from ygc.cloud_storage import MAX_BYTES
from ygc.cloud_backup_preflight import BackupCapacityError,MAX_RESTORE_RAW,preflight_legacy_evidence

MAX_RAW=128*1024*1024
MAX_LINE=8*1024*1024
FORMAT='ygc-postgres-snapshot-v1'


def line(value):
    return (json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False)+'\n').encode()


TYPED_COLUMNS={
    ('accounts','account_projection_outbox','created_at'):'timestamptz',
    ('accounts','account_projection_outbox','delivered_at'):'timestamptz',
    ('chronicle','account_projection_receipts','applied_at'):'timestamptz',
    ('chronicle','ownership_dispute_evidence','content'):'bytea',
}


def encode_cell(value,kind=None):
    if value is None:return None
    if kind=='timestamptz':
        if not isinstance(value,datetime) or value.utcoffset() is None:raise ValueError('Expected timezone-aware timestamp.')
        return {'type':'timestamptz','value':value.astimezone(timezone.utc).isoformat()}
    if kind=='bytea':
        if not isinstance(value,(bytes,memoryview)):raise ValueError('Expected binary value.')
        return {'type':'bytea','value':base64.b64encode(value).decode('ascii')}
    if type(value) not in (str,int,float,bool):raise ValueError('Unsupported scalar type.')
    if type(value)==float and not math.isfinite(value):raise ValueError('Non-finite value.')
    return value


def decode_cell(value,kind=None):
    if value is None:return None
    if kind:
        if not isinstance(value,dict) or set(value)!={'type','value'} or value['type']!=kind or not isinstance(value['value'],str):raise ValueError('Invalid typed value.')
        if kind=='timestamptz':
            decoded=datetime.fromisoformat(value['value'])
            if decoded.utcoffset() is None:raise ValueError('Timestamp requires timezone.')
            return decoded
        if kind=='bytea':return base64.b64decode(value['value'],validate=True)
        raise ValueError('Unknown typed value.')
    return encode_cell(value)


def snapshot(settings,target):
    if target not in TARGETS:raise ValueError('Unknown target.')
    from psycopg import sql
    output=BytesIO();raw=0;digest=hashlib.sha256();counts={};legacy={}
    with connect(settings,target) as con:
        con.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        con.execute("SET LOCAL statement_timeout='30s'")
        con.execute("SET LOCAL lock_timeout='2s'")
        revision=con.execute('SELECT version,checksum FROM ygc_schema_version WHERE id=1').fetchone()
        expected=recorded_schema(target,revision);validate_schema(con,expected)
        if target=='chronicle':legacy=preflight_legacy_evidence(con)
        header={'format':FORMAT,'target':target,'schema_version':revision['version'],'schema_checksum':revision['checksum'],
                'created_at':datetime.now(timezone.utc).isoformat(),'tables':expected['tables']}
        with gzip.GzipFile(fileobj=output,mode='wb',mtime=0) as archive:
            def write(value,hashed=True):
                nonlocal raw
                data=line(value);raw+=len(data)
                if len(data)>MAX_LINE:raise BackupCapacityError('snapshot_line_limit','snapshot_capacity')
                if raw>MAX_RAW:raise BackupCapacityError('snapshot_raw_limit','snapshot_capacity')
                # Chronicle saves must fit the existing restore staging reader.
                # Verification of old archives retains the original MAX_RAW bound.
                if target=='chronicle' and raw>MAX_RESTORE_RAW:
                    raise BackupCapacityError('chronicle_restore_capacity','snapshot_capacity')
                if hashed:digest.update(data)
                archive.write(data)
                if output.tell()>MAX_BYTES:raise BackupCapacityError('snapshot_compressed_limit','snapshot_capacity')
            write(header)
            for table,columns in sorted(expected['tables'].items()):
                counts[table]=0
                with con.cursor(name='snapshot_rows') as cursor:
                    cursor.execute(sql.SQL('SELECT {} FROM {}').format(sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table)))
                    while rows:=cursor.fetchmany(16):
                        for row in rows:
                            write({'table':table,'values':[encode_cell(row[c],TYPED_COLUMNS.get((target,table,c))) for c in columns]});counts[table]+=1
            sequences=[]
            for row in con.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename"):
                name=row['sequencename']
                value=con.execute(sql.SQL('SELECT last_value,is_called FROM {}').format(sql.Identifier(name))).fetchone()
                sequences.append({'name':name,**dict(value)})
            write({'sequences':sequences})
            write({'counts':counts,'sha256':digest.hexdigest()},hashed=False)
    data=output.getvalue()
    if len(data)>MAX_BYTES:raise BackupCapacityError('snapshot_compressed_limit','snapshot_capacity')
    return data,{'target':target,'schema_version':header['schema_version'],'created_at':header['created_at'],
                 'tables':len(counts),'rows':sum(counts.values()),'sha256':hashlib.sha256(data).hexdigest(),
                 'raw_bytes':raw,'compressed_bytes':len(data),**legacy}


def verify_snapshot(data,target,sha256):
    if target not in TARGETS or not isinstance(data,bytes) or not 0<len(data)<=MAX_BYTES or hashlib.sha256(data).hexdigest()!=sha256:
        raise ValueError('Snapshot checksum mismatch.')
    # Stream verification with hard line/total limits; never extract files or run SQL.
    digest=hashlib.sha256();raw=0;sequences_seen=False;footer_seen=False
    with gzip.GzipFile(fileobj=BytesIO(data)) as source:
        def read():
            nonlocal raw
            value=source.readline(MAX_LINE+1);raw+=len(value)
            if len(value)>MAX_LINE or raw>MAX_RAW or (value and not value.endswith(b'\n')):raise ValueError('Invalid snapshot size.')
            return value
        first=read()
        if not first:raise ValueError('Incomplete snapshot.')
        header=json.loads(first);digest.update(first)
        if header.get('format')!=FORMAT or header.get('target')!=target:raise ValueError('Wrong snapshot target/format.')
        expected=recorded_schema(target,{'version':header.get('schema_version'),'checksum':header.get('schema_checksum')})
        if header.get('tables')!=expected['tables']:raise ValueError('Wrong schema columns.')
        counts={table:0 for table in expected['tables']}
        while value:=read():
            row=json.loads(value)
            if not isinstance(row,dict) or footer_seen:raise ValueError('Invalid snapshot record.')
            if set(row)=={'counts','sha256'}:
                if not sequences_seen or row!={'counts':counts,'sha256':digest.hexdigest()}:raise ValueError('Invalid snapshot footer.')
                footer_seen=True;continue
            if set(row)=={'sequences'}:
                if sequences_seen or not isinstance(row['sequences'],list):raise ValueError('Invalid sequences.')
                import re
                names=set()
                for sequence in row['sequences']:
                    if not isinstance(sequence,dict) or set(sequence)!={'name','last_value','is_called'} or not isinstance(sequence['name'],str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,62}',sequence['name']) or sequence['name'] in names or type(sequence['last_value'])!=int or sequence['last_value']<1 or type(sequence['is_called'])!=bool:raise ValueError('Invalid sequence state.')
                    names.add(sequence['name'])
                sequences_seen=True
            else:
                if sequences_seen or set(row)!={'table','values'} or row['table'] not in counts or not isinstance(row['values'],list) or len(row['values'])!=len(expected['tables'][row['table']]):raise ValueError('Invalid snapshot row.')
                for column,cell in zip(expected['tables'][row['table']],row['values']):decode_cell(cell,TYPED_COLUMNS.get((target,row['table'],column)))
                counts[row['table']]+=1
            digest.update(value)
    if not footer_seen:raise ValueError('Incomplete snapshot.')
    return {'target':target,'schema_version':header['schema_version'],'tables':len(counts),'rows':sum(counts.values())}
