"""Offline SQLite maintenance used by the packaged desktop sidecar."""
import ctypes, hashlib, json, os, sqlite3, sys
from pathlib import Path

CURRENT_USER_VERSION=0
MAX_BYTES=int(os.getenv("GROWTHMAP_DB_MAX_BYTES",str(2*1024**3)))
MAX_COUNTS={"projects":100_000,"nodes":5_000_000,"edges":10_000_000,"content_blocks":5_000_000,"action_logs":20_000_000}
ALLOWED_TABLES={"projects","nodes","edges","content_blocks","suggestions","action_logs","provider_configs","branches","agent_artifacts","agent_sessions"}
ALLOWED_INDEXES={"idx_nodes_project","idx_nodes_type","idx_nodes_status","idx_edges_project","idx_edges_from","idx_edges_to","idx_content_blocks_node","idx_suggestions_node","idx_suggestions_status","idx_action_logs_project","idx_action_logs_node","idx_branches_project","idx_agent_artifacts_session","idx_agent_artifacts_status"}
REQUIRED={
 "projects":{"id","name","status","created_at","updated_at"},"nodes":{"id","project_id","title","node_type","status","maturity"},
 "edges":{"id","project_id","from_node_id","to_node_id","relation_type"},"content_blocks":{"id","node_id","block_type","content","order_index"},
 "action_logs":{"id","project_id","actor_type","action_type","created_at"},"provider_configs":{"id","name","provider_type","model_name","enabled"}}

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
 counts={}
 for table,limit in MAX_COUNTS.items():
  counts[table]=int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
  if counts[table]>limit: raise ValueError("database row limits exceeded")
 # Bound potentially hostile values without materializing them.
 for table,column in (("projects","name"),("nodes","title"),("content_blocks","content")):
  if connection.execute(f'SELECT 1 FROM "{table}" WHERE length("{column}")>16777216 LIMIT 1').fetchone(): raise ValueError("database value limits exceeded")
 return {"valid":True,"userVersion":version,"counts":counts,"pageCount":page_count,"pageSize":page_size}

def _open_validated(source):
 source=Path(source);stat=_regular_file(source)
 connection=sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro&immutable=1",uri=True)
 try: meta=_validate_connection(connection,source)
 except Exception: connection.close();raise
 meta.update(size=stat.st_size,sha256=hashlib.sha256(source.read_bytes()).hexdigest())
 return connection,meta

def validate(path):
 connection,meta=_open_validated(path);connection.close();return meta

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
 if len(argv)!=3 or argv[1] not in ("--validate-db","--validated-snapshot-db"): raise SystemExit("maintenance usage error")
 result=validate(argv[2]) if argv[1]=="--validate-db" else validated_snapshot(argv[2],os.environ["GROWTHMAP_MAINTENANCE_DESTINATION"])
 print(json.dumps(result,separators=(",",":")))
