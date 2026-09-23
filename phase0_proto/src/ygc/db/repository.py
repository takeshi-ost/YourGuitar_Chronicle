from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

class Repository:
    def __init__(self, db_path: Path): self.db_path = Path(db_path)
    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path); con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON"); return con
    def init_db(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self.connect() as con: con.executescript(schema_path.read_text(encoding="utf-8"))
    def find_individual(self, maker: str, model: str | None, serial: str):
        with self.connect() as con:
            return con.execute("SELECT * FROM individuals WHERE normalized_manufacturer=? AND COALESCE(normalized_model,'')=COALESCE(?,'') AND normalized_serial=?", (maker,model,serial)).fetchone()
    def create_individual(self, manufacturer, model, serial_number, norm_maker, norm_model, norm_serial) -> int:
        now=utcnow()
        with self.connect() as con:
            cur=con.execute("INSERT INTO individuals (manufacturer,model,serial_number,normalized_manufacturer,normalized_model,normalized_serial,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)", (manufacturer,model,serial_number,norm_maker,norm_model,norm_serial,now,now)); return int(cur.lastrowid)
    def upsert_observation(self, obs: dict[str,Any]):
        with self.connect() as con:
            e=con.execute("SELECT id FROM observations WHERE source_site=? AND source_listing_id=?", (obs['source_site'],obs['source_listing_id'])).fetchone()
            if e: return int(e['id']), False
            cols=['individual_id','manufacturer','model','serial_number','seller','source_site','source_url','source_listing_id','observed_at','listing_date','title','raw_text','serial_confidence','extraction_version','created_at']
            vals=[obs.get(c) for c in cols]
            q=','.join('?' for _ in cols)
            cur=con.execute(f"INSERT INTO observations ({','.join(cols)}) VALUES ({q})", vals); return int(cur.lastrowid), True
    def start_run(self, source_site: str) -> int:
        with self.connect() as con:
            cur=con.execute("INSERT INTO crawl_runs(source_site,started_at,status) VALUES (?,?,'running')", (source_site,utcnow())); return int(cur.lastrowid)
    def finish_run(self, run_id: int, **stats):
        allowed={'pages_discovered','pages_fetched','observations_created','status','error_message'}; sets=[]; vals=[]
        for k,v in stats.items():
            if k in allowed: sets.append(f"{k}=?"); vals.append(v)
        sets.append('finished_at=?'); vals.append(utcnow()); vals.append(run_id)
        with self.connect() as con: con.execute(f"UPDATE crawl_runs SET {', '.join(sets)} WHERE id=?", vals)
    def list_individuals(self):
        with self.connect() as con:
            return list(con.execute("SELECT i.*,COUNT(o.id) observation_count FROM individuals i LEFT JOIN observations o ON o.individual_id=i.id GROUP BY i.id ORDER BY observation_count DESC,i.id"))
    def get_individual(self, individual_id: int):
        with self.connect() as con:
            i=con.execute("SELECT * FROM individuals WHERE id=?",(individual_id,)).fetchone()
            o=list(con.execute("SELECT * FROM observations WHERE individual_id=? ORDER BY COALESCE(listing_date,observed_at),id",(individual_id,)))
            return i,o
    def stats(self):
        with self.connect() as con:
            total=con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            serial=con.execute("SELECT COUNT(*) FROM observations WHERE serial_number IS NOT NULL").fetchone()[0]
            inds=con.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
            repeated=con.execute("SELECT COUNT(*) FROM (SELECT individual_id FROM observations WHERE individual_id IS NOT NULL GROUP BY individual_id HAVING COUNT(*)>=2)").fetchone()[0]
            maxobs=con.execute("SELECT COALESCE(MAX(c),0) FROM (SELECT COUNT(*) c FROM observations WHERE individual_id IS NOT NULL GROUP BY individual_id)").fetchone()[0]
            return {'observations':total,'serial_observations':serial,'serial_extraction_rate':(serial/total*100 if total else 0.0),'individuals':inds,'repeated_individuals':repeated,'max_observations_per_individual':maxobs}
