"""Offline SQLite maintenance used by the packaged desktop sidecar."""
import ctypes, hashlib, json, os, sqlite3, sys
from pathlib import Path
from db.schema_contract import CURRENT_USER_VERSION, COLUMNS, TABLE_CONDITIONAL_COLUMNS, ORM_READ_COLUMNS, ROW_REQUIRED_NON_NULL, applicable_objects, column_matches, normalize_sql, orm_column_problem, provider_selection_contract_problem
MAX_BYTES=int(os.getenv("GROWTHMAP_DB_MAX_BYTES",str(2*1024**3)))
MAX_COUNTS={"projects":100_000,"nodes":5_000_000,"edges":10_000_000,"content_blocks":5_000_000,"action_logs":20_000_000}
CORE_TABLES={"projects","nodes","edges","content_blocks","suggestions","action_logs","provider_configs","provider_selection","branches","agent_artifacts","agent_sessions","agent_grants","agent_receipts","agent_proposals","agent_events","agent_readbacks"}
# These are the accepted immutable Abyss/gameplay extension schemas already
# present in canonical GrowthMap databases. Exact column sets prevent a table
# name alone from bypassing the desktop hostile-schema gate.
EXTENSION_TABLE_COLUMNS={
 "schema_migrations":{"migration_id","checksum","applied_at"},
 "game_content_packs":{"id","pack_key","version","chapter_key","source_revision","source_mapping_path","source_sha256","artifact_sha256","owner_node_ids_json","output_flow_node_id","status","created_at","updated_at"},
 "game_events":{"id","content_pack_id","event_key","chapter_key","section_key","order_index","public_prompt","reveal_tier","canonical_input_json","optional_ui_prep_json","condition_json","next_routing_json","metadata_json"},
 "game_choices":{"id","event_id","choice_key","label","leaf_order","condition_json","outcome_json","effects_json","outputs_json","negative_refs_json","metadata_json"},
 "game_content_releases":{"id","pack_key","content_version","contract_version","release_schema_version","source_mapping_path","source_sha256","artifact_path","artifact_sha256","owner_node_ids_json","event_count","choice_count","serializer_version","replay_verifier_version","release_digest","status","created_at"},
 "player_chapter_runs":{"id","player_id","content_pack_id","chapter_key","run_key","current_event_id","status","state_json","created_at","updated_at"},
 "player_event_resolutions":{"id","run_id","content_pack_id","event_id","choice_id","sequence_no","idempotency_key","content_version","event_key","choice_key","known_state_json","input_refs_json","outcome_json","effects_json","outputs_json","resolved_at","integrity_hash"},
 "player_grant_ledger":{"id","run_id","resolution_id","grant_key","payload_json","granted_at"},
 "player_idempotency_operations":{"id","operation_type","operation_scope","player_id","idempotency_key","request_digest","status","result_json","receipt_json","created_at","completed_at"},
 "player_action_receipts":{"id","run_id","resolution_id","receipt_kind","sequence_no","prev_receipt_hash","receipt_hash","canonical_action_json","canonical_input_json","canonical_result_json","canonical_effects_json","canonical_grants_json","rng_json","external_inputs_json","projection_digest","contract_version","content_version","artifact_sha256","asset_manifest_version","asset_manifest_sha256","rule_version","projection_version","serializer_version","verifier_version","resolved_at"},
 "player_run_replay_pins":{"run_id","release_id","contract_version","content_version","artifact_sha256","asset_manifest_version","asset_manifest_sha256","rule_version","projection_version","serializer_version","replay_verifier_version","genesis_hash","chain_head","next_sequence","created_at"},
}
ALLOWED_TABLES=CORE_TABLES|set(EXTENSION_TABLE_COLUMNS)
ALLOWED_INDEX_TABLES={
 "idx_nodes_project":"nodes","idx_nodes_type":"nodes","idx_nodes_status":"nodes","idx_edges_project":"edges","idx_edges_from":"edges","idx_edges_to":"edges","idx_content_blocks_node":"content_blocks","idx_suggestions_node":"suggestions","idx_suggestions_status":"suggestions","idx_action_logs_project":"action_logs","idx_action_logs_node":"action_logs","idx_branches_project":"branches","idx_agent_artifacts_session":"agent_artifacts","idx_agent_artifacts_status":"agent_artifacts","ux_edges_one_mainline_per_parent":"edges","ux_agent_grants_one_active_workspace":"agent_grants","ix_agent_grants_token_prefix":"agent_grants","ix_agent_grants_project_id":"agent_grants","ix_agent_receipts_grant_id":"agent_receipts","ix_agent_receipts_project_id":"agent_receipts","ux_agent_receipt_idempotency":"agent_receipts","ix_agent_proposals_grant_id":"agent_proposals","ix_agent_proposals_project_id":"agent_proposals","ix_agent_events_grant_id":"agent_events","ix_agent_events_project_id":"agent_events","ix_agent_readbacks_grant_id":"agent_readbacks","ix_agent_readbacks_project_id":"agent_readbacks",
 "idx_game_choices_event":"game_choices","idx_game_events_pack":"game_events","idx_player_idempotency_lookup":"player_idempotency_operations","idx_player_receipts_run":"player_action_receipts","idx_player_runs_player":"player_chapter_runs","idx_resolutions_run":"player_event_resolutions","ux_player_receipt_action_resolution":"player_action_receipts","ux_player_receipt_run_init":"player_action_receipts",
}
ALLOWED_TRIGGER_TABLES={
 "trg_edges_one_mainline_insert":"edges","trg_edges_one_mainline_update":"edges","trg_edges_normalize_null_insert":"edges","trg_edges_normalize_null_update":"edges","trg_provider_revision_insert":"provider_configs","trg_provider_revision_update":"provider_configs",
 "trg_action_receipt_immutable_delete":"player_action_receipts","trg_action_receipt_immutable_update":"player_action_receipts","trg_action_receipt_pins_before_insert":"player_action_receipts","trg_active_content_pack_delete":"game_content_packs","trg_active_content_pack_update":"game_content_packs","trg_active_pack_choice_delete":"game_choices","trg_active_pack_choice_insert":"game_choices","trg_active_pack_choice_update":"game_choices","trg_active_pack_event_delete":"game_events","trg_active_pack_event_insert":"game_events","trg_active_pack_event_update":"game_events","trg_content_release_immutable_delete":"game_content_releases","trg_content_release_immutable_update":"game_content_releases","trg_grant_immutable_delete":"player_grant_ledger","trg_grant_immutable_update":"player_grant_ledger","trg_player_idempotency_immutable_delete":"player_idempotency_operations","trg_player_idempotency_immutable_update":"player_idempotency_operations","trg_replay_pins_immutable_delete":"player_run_replay_pins","trg_replay_pins_immutable_update":"player_run_replay_pins","trg_replay_pins_release_before_insert":"player_run_replay_pins","trg_resolution_immutable_delete":"player_event_resolutions","trg_resolution_immutable_update":"player_event_resolutions",
}
EXTENSION_SQL_SHA256={
 'idx_game_choices_event':'e39c5233dfb0b6d0577733d460d709b91d19c84ddd5c99f68e8e4bf682775acc','idx_game_events_pack':'cbd3a03fcecd293daff2d59b07cc11f39761b14a21147e4bdc7bc805e4b32ead','idx_player_idempotency_lookup':'f3b98aad3c2155e833ec567592c9b054c8a35c647f2d7cbcc0d2fcd137715920','idx_player_receipts_run':'2204577f6903debcc4026767c88f7b007cac49f46e28fd0d0219414903fee33a','idx_player_runs_player':'b5036522c7dabbf494091905e095b425cdaf86ecfb3051d951674afebe57de55','idx_resolutions_run':'7e38271a5a1a5d54fb89a600a68ce9ff79a7b13061b1d323f396dd490b158630','ux_player_receipt_action_resolution':'e983ea2b53a2647ac69fd5eae413a573a1c3b76b223effa900e7d8adba07cf60','ux_player_receipt_run_init':'1f527314225956e250b26532a35995e1f7d6366282c4a960cd7505c83bcc37f9',
 'game_choices':'5981fa0dcb112d737059d0179e92204d92aceaaf2f3b243b58da442bec12d58c','game_content_packs':'e4e8e82f3238cc162b7d09191d394b86b8385514d4d29324d7481b99570aae8f','game_content_releases':'8799dacfcd622adc70495696dffe2ad690e2c7c4c840b2cd829be1467c315027','game_events':'300fc5dac5c2c30867cca514cab8e9b5a9cfe25ad5740fd458e07e4c487d5500','player_action_receipts':'9129943b8a06338823a5b391d8e382257e2080371c93eb6da08cc8956df34c18','player_chapter_runs':'bfffe8f411c123a9d11366d4d9b7d4b1b35dad050f88b9e224ab7b587345b7a6','player_event_resolutions':'aa5856b91d99c871e4ca814d6e83622c24f07941d9ad55ec02872a77c45b4e10','player_grant_ledger':'6d2ee12ab2eaa748d090259dc9c5e68b17fe0d62adedd206e046c3ea0f810a81','player_idempotency_operations':'3331805b05aac1f219dacb92d3e726e63a33d10b79d5070d621cd7cf08240405','player_run_replay_pins':'16543fae68bd0ba7679e01c1611ec4aac330c60abf2d77477848ae46b8672bdd','schema_migrations':'358175f7a55bf13134311d0e433b2e6adaec0865c908fe3a3b4b3897d7064b13',
 'trg_action_receipt_immutable_delete':'548fac38db24707efa603837d5dd8917d9620a070e1188fe188072699ece56c5','trg_action_receipt_immutable_update':'ea6caa6f0b194ae5dab11a00446504b54e81a33d1531214d8d381146fa955fd3','trg_action_receipt_pins_before_insert':'03ee702b611f09a003f789af8948d7d43af3719d523bcea6553e7c332d383fa1','trg_active_content_pack_delete':'e74387f247a8493046d793026388aa34ca202b6a5e7400defc23dd9262f5257b','trg_active_content_pack_update':'d2de23359b1db95468cd78e2815dc42e224ef3f2245b6566559c7863239a7cce','trg_active_pack_choice_delete':'cb265ab617dc1a4bee811eb9771c75c6eb88f997ed8f33efdd22009518be4092','trg_active_pack_choice_insert':'f0b87077b0079bea9c08360a12ac4be7b6547baf7565b963ab8ab463ab585793','trg_active_pack_choice_update':'466fc312307c7b3e29f684328ee791c79122b232cef3c4af7b015fb46efb2f38','trg_active_pack_event_delete':'d6c97f74db0f3e6eee55a0bbcac838a61158a8cc3a7bcd3a5f9bb503f25d87a9','trg_active_pack_event_insert':'dbf485a307790f85e683123d79b63adcbb9637984fc53dd437dc2edc8ad387bf','trg_active_pack_event_update':'4e487b47217bc748ac08ca5e53641b0ac33415bc7d6c9b3be96ddbc2ee4f509c','trg_content_release_immutable_delete':'423726d14a733cba383650a657fead038200531ef6cfd8efe43c5f3f78bc8bda','trg_content_release_immutable_update':'42536a2dc970c32cfa5444e1c75922d73b48ce087f3641948ca8237253f14d60','trg_grant_immutable_delete':'fa40a0550c45fe93bffa1411a14a15111bedc4244094ab14ce0c5ea7a4265b83','trg_grant_immutable_update':'96e290900bd9524f3a7fd828a95dcdba2c149671a304594901965d8a2be1bfef','trg_player_idempotency_immutable_delete':'fe4c97a6adeb47e162b74183b3f133646b77ebcf8db421b8a0a96f8a80798b79','trg_player_idempotency_immutable_update':'3e8c2d25625ad3f23345c48fdb71a0632aa3cd90f85f0d446a7dfc163dc039cf','trg_replay_pins_immutable_delete':'129b01e392f94986a52adbec93b766b8eb0f623510e0e1817e6ebfb8314fb33d','trg_replay_pins_immutable_update':'447c449e18946d8188c7cedfb2026905efb0ceceb209e27f93bfc79777f3a64c','trg_replay_pins_release_before_insert':'4c66b35de4c75ef49e8a9ebbafb129df82552e85d67340ffbca2af2faa12ee0f','trg_resolution_immutable_delete':'0a942781f3faf2d27fa852cda8038f881b76d84dadeb7fc599157f0e55f0bc43','trg_resolution_immutable_update':'e1c75e17f5990a80546209c6b3154756f170f15476deb4a9fadd67a91144713e',
}
REQUIRED={
 "projects":{"id","name","status","created_at","updated_at"},
 "nodes":{"id","project_id","title","node_type","status","maturity"},
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
  if name in EXTENSION_SQL_SHA256:
   digest=hashlib.sha256(" ".join(sql.strip().lower().split()).encode()).hexdigest() if sql else ""
   if digest!=EXTENSION_SQL_SHA256[name]: raise ValueError("database contains an incompatible extension schema object")
  if kind=="table" and name in ALLOWED_TABLES and sql and not sql.lstrip().upper().startswith("CREATE VIRTUAL"):
   expected=EXTENSION_TABLE_COLUMNS.get(name)
   if expected is not None:
    actual={row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')}
    if actual!=expected: raise ValueError("database contains an incompatible extension table")
   if name=="provider_selection":
    problem=provider_selection_contract_problem(connection.execute('PRAGMA table_info("provider_selection")').fetchall(),connection.execute('PRAGMA foreign_key_list("provider_selection")').fetchall(),sql)
    if problem is not None: raise ValueError("database contains an incompatible provider selection authority")
   continue
  if kind=="index" and ALLOWED_INDEX_TABLES.get(name)==table: continue
  if kind=="trigger" and ALLOWED_TRIGGER_TABLES.get(name)==table: continue
  raise ValueError("database contains an unapproved schema object")
 temp=connection.execute("SELECT COUNT(*) FROM sqlite_temp_schema").fetchone()[0]
 if temp: raise ValueError("temporary schema objects are not allowed")
 quick=connection.execute("PRAGMA quick_check").fetchall()
 if quick!=[("ok",)]: raise ValueError("SQLite quick check failed")
 if connection.execute("PRAGMA foreign_key_check").fetchall(): raise ValueError("foreign key check failed")
 if connection.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='provider_selection'").fetchone():
  rows=connection.execute("SELECT singleton_id,provider_id,selection_revision FROM provider_selection").fetchall()
  if rows!=[(1,None,1)] and (len(rows)!=1 or rows[0][0]!=1 or not isinstance(rows[0][2],int) or rows[0][2]<1 or rows[0][2]>9007199254740991): raise ValueError("database contains an invalid provider selection authority row")
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
 counts["activeProjects"]=int(connection.execute("SELECT COUNT(*) FROM projects WHERE status='active'").fetchone()[0])
 # Bound potentially hostile values without materializing them.
 for table,column in (("projects","name"),("nodes","title"),("content_blocks","content")):
  if connection.execute(f'SELECT 1 FROM "{table}" WHERE length("{column}")>16777216 LIMIT 1').fetchone(): raise ValueError("database value limits exceeded")
 return {"valid":True,"userVersion":version,"counts":counts,"pageCount":page_count,"pageSize":page_size}

def _open_validated(source):
 source=Path(source);stat=_regular_file(source)
 connection=sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro&immutable=1",uri=True)
 try: meta=_validate_connection(connection,source)
 except Exception: connection.close();raise
 # Filesystem identities cross a JSON/JavaScript boundary in Electron. Keep
 # them as canonical decimal strings so Windows 64-bit file IDs are not
 # rounded by JavaScript Number before being returned as install evidence.
 meta.update(size=stat.st_size,sha256=hashlib.sha256(source.read_bytes()).hexdigest(),device=str(stat.st_dev),inode=str(stat.st_ino))
 return connection,meta

def validate(path):
 connection,meta=_open_validated(path);connection.close();return meta

def stable_validate(path):
 """Validate one unchanged regular-file identity and bind metadata to its exact bytes."""
 source=Path(path);before=_regular_file(source);meta=validate(source);after=_regular_file(source)
 identity=lambda stat:(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_nlink)
 if identity(before)!=identity(after) or meta["size"]!=after.st_size or meta["sha256"]!=hashlib.sha256(source.read_bytes()).hexdigest():raise ValueError("database changed during stable validation")
 final=_regular_file(source)
 if identity(after)!=identity(final):raise ValueError("database changed during stable validation")
 return meta

def schema_status(path):
 """Inspect only the migration-owned schema surface without opening SQLite writable."""
 source=Path(path)
 if not source.exists(): return {"exists":False,"compatible":False,"migrationNeeded":True,"reasons":["database_missing"]}
 connection,meta=_open_validated(source)
 try:
  reasons=[]
  for table,contract in ORM_READ_COLUMNS.items():
   rows={row[1]:row for row in connection.execute(f'PRAGMA table_info("{table}")')}
   for column,expected in contract.items():
    problem=orm_column_problem(rows.get(column),expected)
    if problem:reasons.append(f"{problem}_orm_column:{table}.{column}")
  for table,columns in ROW_REQUIRED_NON_NULL.items():
   present={row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
   for column in columns:
    # Missing tables/columns are already reported by the strict ORM contract;
    # avoid turning a coherent rejection into an inspection exception.
    if column in present and connection.execute(f'SELECT 1 FROM "{table}" WHERE "{column}" IS NULL LIMIT 1').fetchone():reasons.append(f"null_data:{table}.{column}")
  if connection.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='agent_grants'").fetchone():
   expiry=next((row for row in connection.execute('PRAGMA table_info("agent_grants")') if row[1]=="expires_at"),None)
   if expiry is not None and bool(expiry[3]):reasons.append("incompatible_column:agent_grants.expires_at")
  migration_specs=list(COLUMNS)
  migration_specs.extend(spec for spec in TABLE_CONDITIONAL_COLUMNS if connection.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?",(spec[0],)).fetchone())
  for spec in migration_specs:
   row=next((item for item in connection.execute(f'PRAGMA table_info("{spec[0]}")') if item[1]==spec[1]),None)
   if row is None:reasons.append(f"column:{spec[0]}.{spec[1]}")
   elif not column_matches(row,spec):reasons.append(f"incompatible_column:{spec[0]}.{spec[1]}")
  existing_tables={row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
  for name,sql in applicable_objects(existing_tables).items():
   row=connection.execute("SELECT sql FROM sqlite_schema WHERE name=?",(name,)).fetchone()
   if row is None:reasons.append(f"object:{name}")
   elif normalize_sql(row[0])!=normalize_sql(sql):reasons.append(f"incompatible_object:{name}")
  if meta["userVersion"]!=CURRENT_USER_VERSION:reasons.append(f"user_version:{meta['userVersion']}")
  return {"exists":True,"compatible":not reasons,"migrationNeeded":bool(reasons),"reasons":reasons,"sha256":meta["sha256"],"size":meta["size"],"userVersion":meta["userVersion"]}
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
  source_after=_regular_file(src)
  source_sha_after=hashlib.sha256(src.read_bytes()).hexdigest()
  if source_after.st_size!=source_meta["size"] or source_sha_after!=source_meta["sha256"]:raise ValueError("snapshot source changed during capture")
  durability=_durability(dst,parent)
  final=validate(dst);final["durability"]=durability;final["sourceSha256"]=source_meta["sha256"];final["sourceSize"]=source_meta["size"];return final
 except Exception:
  try: writer.close()
  except Exception: pass
  try: reader.close()
  except Exception: pass
  try: dst.unlink(missing_ok=True)
  except Exception as cleanup: raise RuntimeError("snapshot cleanup failed; recovery required") from cleanup
  raise

def _identity(stat):
 # POSIX identity is stable and nonzero. Windows filesystems may report zero;
 # there digest/size/link/regular metadata remains the supported equivalent.
 return {"device":str(stat.st_dev),"inode":str(stat.st_ino),"meaningful":bool(stat.st_dev or stat.st_ino)}

def install_database(staging,live,_test_before_install=None):
 """Capture, validate and atomically install one exact staged database object."""
 source=Path(staging);target=Path(live);parent=_safe_parent(target)
 old=Path(os.environ["GROWTHMAP_MAINTENANCE_OLD"]);captured=Path(os.environ["GROWTHMAP_MAINTENANCE_CAPTURE"])
 expected_sha=os.environ.get("GROWTHMAP_EXPECTED_SHA256");expected_size=int(os.environ["GROWTHMAP_EXPECTED_SIZE"])
 expected_device=int(os.environ["GROWTHMAP_EXPECTED_DEVICE"]);expected_inode=int(os.environ["GROWTHMAP_EXPECTED_INODE"])
 maximum=int(os.environ["GROWTHMAP_MAX_ACTIVE_PROJECTS"]) if os.environ.get("GROWTHMAP_MAX_ACTIVE_PROJECTS") else None
 if old.exists() or captured.exists():raise ValueError("replacement destination already exists")
 source_stat=_regular_file(source)
 if _identity(source_stat)["meaningful"] and (source_stat.st_dev,source_stat.st_ino)!=(expected_device,expected_inode):raise ValueError("staging identity changed before install")
 meta=validated_snapshot(source,captured)
 after=_regular_file(source)
 if _identity(source_stat)["meaningful"] and (source_stat.st_dev,source_stat.st_ino)!=(after.st_dev,after.st_ino):raise ValueError("staging identity changed during capture")
 captured_stat=_regular_file(captured);captured_identity=_identity(captured_stat)
 if _test_before_install is not None:_test_before_install(captured)
 before_install=_regular_file(captured)
 if captured_identity["meaningful"] and (before_install.st_dev,before_install.st_ino)!=(captured_stat.st_dev,captured_stat.st_ino):raise ValueError("captured identity changed before install")
 if before_install.st_size!=captured_stat.st_size:raise ValueError("captured size changed before install")
 staged=stable_validate(captured)
 if staged["sha256"]!=meta["sha256"] or staged["size"]!=meta["size"]:raise ValueError("captured database changed")
 if expected_sha and (meta["sourceSha256"]!=expected_sha or meta["sourceSize"]!=expected_size):raise ValueError("database source changed after validation")
 if maximum is not None and staged["counts"]["activeProjects"]>maximum:raise ValueError("database exceeds active project limit")
 os.replace(target,old)
 try:
  os.replace(captured,target);target_stat=_regular_file(target);installed=stable_validate(target)
  if captured_identity["meaningful"] and (target_stat.st_dev,target_stat.st_ino)!=(captured_stat.st_dev,captured_stat.st_ino):raise ValueError("installed database identity changed")
  if installed["sha256"]!=staged["sha256"] or installed["size"]!=staged["size"]:raise ValueError("installed database changed")
  if maximum is not None and installed["counts"]["activeProjects"]>maximum:raise ValueError("installed database exceeds active project limit")
  _durability(target,parent)
  installed["identity"]=_identity(target_stat)
  return {"installed":installed,"old":str(old)}
 except Exception:
  try:
   if target.exists():os.replace(target,Path(str(captured)+".failed"))
   os.replace(old,target);_durability(target,parent)
  except Exception as rollback:raise RuntimeError("database rollback failed; recovery required") from rollback
  raise

def main(argv):
 if os.getenv("GROWTHMAP_DESKTOP_MODE")!="1": raise SystemExit("desktop mode required")
 if len(argv)!=3 or argv[1] not in ("--validate-db","--stable-validate-db","--validated-snapshot-db","--install-db","--entitlement-status","--schema-status"): raise SystemExit("maintenance usage error")
 if argv[1]=="--entitlement-status":
  # No database is opened. This is the same cryptographic verifier used by the API.
  from desktop.startup_verdict import effective_entitlement
  result=effective_entitlement().public()
 elif argv[1]=="--validate-db": result=validate(argv[2])
 elif argv[1]=="--stable-validate-db": result=stable_validate(argv[2])
 elif argv[1]=="--schema-status": result=schema_status(argv[2])
 elif argv[1]=="--install-db": result=install_database(argv[2],os.environ["GROWTHMAP_MAINTENANCE_DESTINATION"])
 else: result=validated_snapshot(argv[2],os.environ["GROWTHMAP_MAINTENANCE_DESTINATION"])
 print(json.dumps(result,separators=(",",":")))
