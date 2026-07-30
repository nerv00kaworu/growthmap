"""Offline SQLite maintenance used by the packaged desktop sidecar."""
import ctypes, hashlib, json, os, sqlite3, sys
from pathlib import Path

CURRENT_USER_VERSION=2
MAX_BYTES=int(os.getenv("GROWTHMAP_DB_MAX_BYTES",str(2*1024**3)))
MAX_COUNTS={"projects":100_000,"nodes":5_000_000,"edges":10_000_000,"content_blocks":5_000_000,"action_logs":20_000_000}
ALLOWED_TABLES={"projects","nodes","edges","content_blocks","suggestions","action_logs","provider_configs","branches","agent_artifacts","agent_sessions","agent_grants","agent_receipts","agent_proposals","agent_events","agent_readbacks"}
ALLOWED_INDEXES={"idx_nodes_project","idx_nodes_type","idx_nodes_status","idx_edges_project","idx_edges_from","idx_edges_to","idx_content_blocks_node","idx_suggestions_node","idx_suggestions_status","idx_action_logs_project","idx_action_logs_node","idx_branches_project","idx_agent_artifacts_session","idx_agent_artifacts_status","ux_edges_one_mainline_per_parent","ix_agent_grants_token_prefix","ix_agent_grants_project_id","ix_agent_receipts_grant_id","ix_agent_receipts_project_id","ux_agent_receipt_idempotency","ix_agent_proposals_grant_id","ix_agent_proposals_project_id","ix_agent_events_grant_id","ix_agent_events_project_id","ix_agent_readbacks_grant_id","ix_agent_readbacks_project_id"}
ALLOWED_TRIGGERS={"trg_edges_one_mainline_insert","trg_edges_one_mainline_update","trg_edges_normalize_null_insert","trg_edges_normalize_null_update"}
REQUIRED={
 "projects":{"id","name","status","created_at","updated_at"},"nodes":{"id","project_id","title","node_type","status","maturity"},
 "edges":{"id","project_id","from_node_id","to_node_id","relation_type"},"content_blocks":{"id","node_id","block_type","content","order_index"},
 "action_logs":{"id","project_id","actor_type","action_type","created_at"},"provider_configs":{"id","name","provider_type","model_name","enabled"}}
READBACK_CORE={"id":("VARCHAR(36)",True,None,1),"grant_id":("VARCHAR(36)",True,None,0),"project_id":("VARCHAR(36)",True,None,0),"target_node_id":("VARCHAR(36)",False,None,0),"commit_refs":("JSON",True,None,0),"files":("JSON",True,None,0),"tests":("JSON",True,None,0),"decisions":("JSON",True,None,0),"risks":("JSON",True,None,0),"todos":("JSON",True,None,0),"evidence":("JSON",True,None,0),"summary":("TEXT",False,None,0),"created_at":("DATETIME",False,None,0)}
READBACK_V2={"based_on_project_revision":("INTEGER",True,"1",0),"context_snapshot_digest":("VARCHAR(64)",True,"",0),"objective":("TEXT",True,"",0),"current_project_revision":("INTEGER",True,"1",0),"context_stale":("BOOLEAN",True,"1",0)}
READBACK_FKS={("grant_id","agent_grants","id","NO ACTION","CASCADE","NONE"),("project_id","projects","id","NO ACTION","CASCADE","NONE"),("target_node_id","nodes","id","NO ACTION","SET NULL","NONE")}
READBACK_INDEXES={"ix_agent_readbacks_grant_id":"grant_id","ix_agent_readbacks_project_id":"project_id"}

def _literal_default(value):
 if value is None:return None
 raw=str(value).strip()
 while len(raw)>=2 and raw[0]=='(' and raw[-1]==')':raw=raw[1:-1].strip()
 if raw.upper()=='NULL':return None
 if raw.startswith("'") and raw.endswith("'"):
  inner=raw[1:-1]
  if "'" in inner.replace("''",""):raise ValueError("nonliteral column default")
  return inner.replace("''", "'")
 if raw in {'0','1'} or (raw.startswith('-') and raw[1:].isdigit()) or raw.isdigit():return raw
 raise ValueError("nonliteral column default")

def _readback_drift(connection,include_v2=True):
 reasons=[];row=connection.execute("SELECT type FROM sqlite_schema WHERE name='agent_readbacks'").fetchone()
 if row!=("table",):return ["table:agent_readbacks"]
 info={r[1]:(str(r[2]).upper(),bool(r[3]),_literal_default(r[4]),int(r[5])) for r in connection.execute('PRAGMA table_info("agent_readbacks")')}
 expected={**READBACK_CORE,**(READBACK_V2 if include_v2 else {})}
 for name,spec in expected.items():
  if info.get(name)!=spec:reasons.append(f"column:agent_readbacks.{name}")
 fks={(r[3],r[2],r[4],str(r[5]).upper(),str(r[6]).upper(),str(r[7]).upper()) for r in connection.execute('PRAGMA foreign_key_list("agent_readbacks")')}
 if fks!=READBACK_FKS:reasons.append("foreign_keys:agent_readbacks")
 indexes={r[1]:r for r in connection.execute('PRAGMA index_list("agent_readbacks")')}
 named={name for name,row in indexes.items() if row[3]=='c'}
 if named!=set(READBACK_INDEXES) or any(row[3] not in {'c','pk'} or (row[3]=='pk' and (not bool(row[2]) or bool(row[4]))) for row in indexes.values()) or sum(1 for row in indexes.values() if row[3]=='pk')>1:reasons.append("indexes:agent_readbacks")
 for name,column in READBACK_INDEXES.items():
  idx=indexes.get(name)
  if not idx or bool(idx[2]) or bool(idx[4]):reasons.append(f"index:{name}");continue
  keys=[r for r in connection.execute(f'PRAGMA index_xinfo("{name}")') if r[5]]
  if len(keys)!=1 or keys[0][2]!=column or keys[0][1]<0:reasons.append(f"index:{name}")
 return reasons

def _attributes(path):
 if os.name!="nt": return 0
 value=ctypes.windll.kernel32.GetFileAttributesW(str(path))
 if value==0xFFFFFFFF: raise ValueError("path attributes unavailable")
 return value

def _safe_parent(path):
 parent=path.resolve().parent
 if str(parent).startswith("\\\\"): raise ValueError("network paths are not allowed")
 if _attributes(parent)&0x400: raise ValueError("destination parent is a reparse point")
 if not parent.is_dir() or parent.is_symlink(): raise ValueError("destination parent is unsafe")
 return parent

def _regular_file(path):
 path=Path(path)
 if str(path).startswith("\\\\"): raise ValueError("network paths are not allowed")
 if os.name=="nt":
  current=path
  while current!=current.parent:
   if _attributes(current)&0x400: raise ValueError("database path contains a reparse point")
   current=current.parent
 if _attributes(path)&0x400: raise ValueError("database is a reparse point")
 stat=path.lstat()
 if path.is_symlink() or not path.is_file() or stat.st_nlink!=1: raise ValueError("database must be a single-link regular file")
 if stat.st_size<100 or stat.st_size>MAX_BYTES: raise ValueError("database size is outside limits")
 with path.open("rb") as handle:
  if handle.read(16)!=b"SQLite format 3\x00": raise ValueError("not a SQLite database")
 return stat

def _configure(connection):
 connection.execute("PRAGMA trusted_schema=OFF")
 connection.execute("PRAGMA query_only=ON")

def _validate_connection(connection,source):
 _configure(connection)
 page_count=int(connection.execute("PRAGMA page_count").fetchone()[0]);page_size=int(connection.execute("PRAGMA page_size").fetchone()[0])
 if page_count<=0 or page_size<=0 or page_count*page_size>MAX_BYTES: raise ValueError("database page limits exceeded")
 objects=connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_autoindex_%'").fetchall()
 for kind,name,table,sql in objects:
  if kind=="table" and name in ALLOWED_TABLES and sql and not sql.lstrip().upper().startswith("CREATE VIRTUAL"): continue
  if kind=="index" and name in ALLOWED_INDEXES and table in ALLOWED_TABLES: continue
  if kind=="trigger" and name in ALLOWED_TRIGGERS and table=="edges": continue
  raise ValueError("database contains an unapproved schema object")
 temp=connection.execute("SELECT COUNT(*) FROM sqlite_temp_schema").fetchone()[0]
 if temp: raise ValueError("temporary schema objects are not allowed")
 quick=connection.execute("PRAGMA quick_check").fetchall()
 if quick!=[("ok",)]: raise ValueError("SQLite quick check failed")
 if connection.execute("PRAGMA foreign_key_check").fetchall(): raise ValueError("foreign key check failed")
 version=int(connection.execute("PRAGMA user_version").fetchone()[0])
 if version>CURRENT_USER_VERSION: raise ValueError("database schema is newer than this application")
 for table,columns in REQUIRED.items():
  row=connection.execute("SELECT type FROM sqlite_schema WHERE name=?",(table,)).fetchone()
  if row!=("table",): raise ValueError("required table is missing")
  actual={item[1] for item in connection.execute(f'PRAGMA table_info("{table}")')}
  if columns-actual: raise ValueError("required columns are missing")
 if version>=2 and _readback_drift(connection):raise ValueError("current agent_readbacks contract is incompatible")
 if version==1 and connection.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='agent_readbacks'").fetchone() and _readback_drift(connection,False):raise ValueError("legacy agent_readbacks core is incompatible")
 # SQLite foreign keys do not express edge.project_id == endpoint.project_id.
 if connection.execute("SELECT 1 FROM edges e LEFT JOIN nodes f ON f.id=e.from_node_id LEFT JOIN nodes t ON t.id=e.to_node_id WHERE f.id IS NULL OR t.id IS NULL OR e.project_id!=f.project_id OR e.project_id!=t.project_id LIMIT 1").fetchone(): raise ValueError("edge crosses project boundary")
 counts={}
 for table,limit in MAX_COUNTS.items():
  counts[table]=int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
  if counts[table]>limit: raise ValueError("database row limits exceeded")
 # A current-schema import must also be readable through the authoritative
 # projects API after restart. Older valid schemas remain migration inputs.
 project_columns={row[1] for row in connection.execute('PRAGMA table_info("projects")')}
 api_columns={"id","name","root_node_id","status","settings","created_at","updated_at"}
 if api_columns<=project_columns and connection.execute("SELECT 1 FROM projects WHERE id IS NULL OR id='' OR name IS NULL OR root_node_id IS NULL OR root_node_id='' OR status IS NULL OR settings IS NULL OR created_at IS NULL OR updated_at IS NULL LIMIT 1").fetchone():
  raise ValueError("project contains fields required by the application API")
 project_ids=[row[0] for row in connection.execute("SELECT id FROM projects ORDER BY id")]
 project_id_sha256=hashlib.sha256(json.dumps(project_ids,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
 # Bound potentially hostile values without materializing them.
 for table,column in (("projects","name"),("nodes","title"),("content_blocks","content")):
  if connection.execute(f'SELECT 1 FROM "{table}" WHERE length("{column}")>16777216 LIMIT 1').fetchone(): raise ValueError("database value limits exceeded")
 return {"valid":True,"userVersion":version,"counts":counts,"projectIdSha256":project_id_sha256,"pageCount":page_count,"pageSize":page_size}

def _open_validated(source):
 source=Path(source);stat=_regular_file(source)
 connection=sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro&immutable=1",uri=True)
 try: meta=_validate_connection(connection,source)
 except Exception: connection.close();raise
 meta.update(size=stat.st_size,sha256=hashlib.sha256(source.read_bytes()).hexdigest())
 return connection,meta

def validate(path):
 connection,meta=_open_validated(path);connection.close();return meta

def schema_status(path):
 """Inspect only the migration-owned schema surface without opening SQLite writable."""
 source=Path(path)
 if not source.exists(): return {"exists":False,"migrationNeeded":True,"reasons":["database_missing"]}
 connection,meta=_open_validated(source)
 try:
  columns={table:{row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')} for table in ("projects","nodes","edges","content_blocks","branches","provider_configs","agent_readbacks") if connection.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?",(table,)).fetchone()}
  objects={row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type IN ('index','trigger')")}
  reasons=[]
  for table,column in (("nodes","branch_id"),("nodes","workflow_status"),("nodes","file_paths"),("provider_configs","secret_env_key"),("projects","revision"),("nodes","revision"),("edges","revision"),("content_blocks","revision"),("branches","revision")):
   if column not in columns[table]: reasons.append(f"column:{table}.{column}")
  reasons.extend(_readback_drift(connection,True))
  for name in ("ux_edges_one_mainline_per_parent","trg_edges_one_mainline_insert","trg_edges_one_mainline_update","trg_edges_normalize_null_insert","trg_edges_normalize_null_update"):
   if name not in objects: reasons.append(f"object:{name}")
  return {"exists":True,"migrationNeeded":bool(reasons),"reasons":reasons,"sha256":meta["sha256"],"size":meta["size"],"userVersion":meta["userVersion"]}
 finally: connection.close()

def _durability(file,parent):
 if os.name=="nt":
  # Python's os.fsync on a read-only Windows descriptor can fail with EBADF.
  # Open a writable, non-truncating handle and flush it through the Win32 API.
  with file.open("r+b",buffering=0) as handle:
   import msvcrt
   raw=msvcrt.get_osfhandle(handle.fileno())
   if not ctypes.windll.kernel32.FlushFileBuffers(ctypes.c_void_p(raw)):
    raise ctypes.WinError()
  return {"fileFlush":"FlushFileBuffers","directoryFlush":"unsupported-windows-best-effort"}
 with file.open("rb") as handle: os.fsync(handle.fileno())
 fd=os.open(parent,os.O_RDONLY)
 try: os.fsync(fd)
 finally: os.close(fd)
 return {"fileFsync":True,"directoryFsync":True}

def validated_snapshot(source,destination):
 src=Path(source);dst=Path(destination);parent=_safe_parent(dst)
 if dst.exists(): raise ValueError("snapshot destination already exists")
 reader,source_meta=_open_validated(src)
 writer=sqlite3.connect(str(dst))
 try:
  reader.backup(writer);writer.commit();writer.close();reader.close()
  durability=_durability(dst,parent)
  final=validate(dst);final["durability"]=durability;return final
 except Exception:
  try: writer.close()
  except Exception: pass
  try: reader.close()
  except Exception: pass
  try: dst.unlink(missing_ok=True)
  except Exception as cleanup: raise RuntimeError("snapshot cleanup failed; recovery required") from cleanup
  raise

def main(argv):
 if os.getenv("GROWTHMAP_DESKTOP_MODE")!="1": raise SystemExit("desktop mode required")
 if len(argv)!=3 or argv[1] not in ("--validate-db","--validated-snapshot-db","--entitlement-status","--schema-status"): raise SystemExit("maintenance usage error")
 if argv[1]=="--entitlement-status":
  # No database is opened. This is the same cryptographic verifier used by the API.
  from desktop.entitlements import peek_current_entitlement
  result=peek_current_entitlement().public()
 elif argv[1]=="--validate-db": result=validate(argv[2])
 elif argv[1]=="--schema-status": result=schema_status(argv[2])
 else: result=validated_snapshot(argv[2],os.environ["GROWTHMAP_MAINTENANCE_DESTINATION"])
 print(json.dumps(result,separators=(",",":")))
