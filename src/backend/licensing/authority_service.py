"""Fixed-config production composition root and local custody adapters.

The local anchor and SQLite guards reduce pathname/race mistakes; neither is cryptographic
rollback proof. Same-inode mutation by the Authority process/UID is accepted as Authority-process
compromise and exact ACL/mount/FUSE/overlay/durability behavior remains a deployment drill gate.
"""
from __future__ import annotations
import fcntl, hashlib, json, os, re, secrets, sqlite3, stat, threading
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from .authority import AUTHORITY_SCHEMA_SCRIPT, AuthorityDatabaseBroker, LicenseAuthority
from .pem_signer import canonical, require_linux_loader_primitives, _open_parent, _stable
from .signer_ceremony import OfflineFixtureMonotonicAnchor, validate_anchor_claim

CONFIG_FIELDS={"schema_version","authority_id","expected_uid","approved_directory_uids","private_key_path","database_path","reviewed_public_key_path","reviewed_public_key_sha256","descriptor_path","ceremony_record_path","authorized_reviewers","release_sha256","deployment_config_sha256","anchor","listen"}
ANCHOR_FIELDS={"provider","path","expected_uid"};LISTEN_FIELDS={"host","port"}
_SQLITE_CONNECT=sqlite3.connect
_LOCK_TIMEOUT_SECONDS=1.0  # Closed production constant; saturation is an operations blocker.
_SETUP_PRAGMA_WRITES=frozenset({
    ("journal_mode","delete"),("foreign_keys","on"),("busy_timeout","30000"),
    ("synchronous","full"),("temp_store","memory"),("trusted_schema","off"),
    ("locking_mode","normal"),("query_only","off"),("secure_delete","on"),
})
# SQLITE_PRAGMA reports normalized pragma names and semantic arguments, including for quoted,
# schema-qualified, parenthesized and mixed-case source forms. Application code gets only these
# no-argument reads; every argument-bearing PRAGMA is denied by default.
_READ_ONLY_PRAGMAS=frozenset({
    "database_list","journal_mode","synchronous","temp_store","foreign_keys",
    "trusted_schema","locking_mode","query_only","secure_delete","busy_timeout",
})
_TOP_LEVEL_SQL_PREFIX=re.compile(r"(?:\s+|--[^\r\n]*(?:\r?\n|$)|/\*.*?\*/)*",re.DOTALL)

def _top_level_keyword(sql):
    if type(sql) is not str:return ""
    start=_TOP_LEVEL_SQL_PREFIX.match(sql).end();match=re.match(r"[A-Za-z]+",sql[start:])
    return match.group(0).upper() if match else ""

def _absolute(v,name):
    if type(v) is not str or not Path(v).is_absolute():raise RuntimeError(name+"_must_be_absolute")
    return Path(v)

def _read_all(fd,max_bytes):
    out=bytearray()
    while len(out)<=max_bytes:
        b=os.read(fd,min(65536,max_bytes+1-len(out)))
        if not b:break
        out.extend(b)
    return bytes(out)

def _file_identity(st):return (st.st_dev,st.st_ino,st.st_mode,st.st_uid,st.st_gid,st.st_nlink)

def _read_fixed(path:Path,*,expected_uid:int,approved_directory_uids=None,max_bytes=262144,mode=0o400,mutation_hook=None)->bytes:
    require_linux_loader_primitives()
    if not path.is_absolute():raise RuntimeError("fixed_path_must_be_absolute")
    allowed=set(approved_directory_uids or {0,expected_uid});parent,name=_open_parent(path,allowed);parent_id=_file_identity(os.fstat(parent));fd=-1
    try:
        fd=os.open(name,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent);a=os.fstat(fd)
        if not stat.S_ISREG(a.st_mode) or a.st_uid!=expected_uid or stat.S_IMODE(a.st_mode)!=mode or a.st_nlink!=1 or not 0<a.st_size<=max_bytes:raise RuntimeError("fixed_file_policy_invalid")
        first=_read_all(fd,max_bytes)
        if mutation_hook:mutation_hook(parent,name,fd)
        os.lseek(fd,0,0);second=_read_all(fd,max_bytes);b=os.fstat(fd);current=_stat_at(parent,name)
        if first!=second or len(first)!=a.st_size or not _stable(a,b) or _file_identity(b)!=_file_identity(current) or _file_identity(os.fstat(parent))!=parent_id:raise RuntimeError("fixed_file_changed")
        return first
    except OSError as e:raise RuntimeError("fixed_file_open_failed") from e
    finally:
        if fd>=0:os.close(fd)
        os.close(parent)

def _reject_duplicates(pairs):
    out={}
    for key,value in pairs:
        if key in out:raise ValueError("duplicate_json_member")
        out[key]=value
    return out

def _loads(data:bytes,error:str):
    try:return json.loads(data,object_pairs_hook=_reject_duplicates)
    except Exception as e:raise RuntimeError(error) from e

def _json(data:bytes,fields:set[str],error:str):
    value=_loads(data,error)
    if type(value) is not dict or set(value)!=fields:raise RuntimeError(error)
    return value

def _stat_at(parent_fd,name):return os.stat(name,dir_fd=parent_fd,follow_symlinks=False)

def _validate_regular(st,uid,mode,error,*,max_bytes=None,allow_empty=True):
    if (not stat.S_ISREG(st.st_mode) or st.st_uid!=uid or stat.S_IMODE(st.st_mode)!=mode or st.st_nlink!=1
            or (max_bytes is not None and (st.st_size>max_bytes or (not allow_empty and st.st_size<=0)))):raise RuntimeError(error)

class TrustedDatabaseGuard:
    """Hold trusted parent+DB descriptors through SQLite bootstrap and revalidate sidecars."""
    SIDECARS=("-wal","-shm","-journal")
    def __init__(self,path:Path,expected_uid:int,approved_uids:frozenset[int],max_bytes=16*1024**3):
        self.path=path;self.uid=expected_uid;self.approved=approved_uids;self.max_bytes=max_bytes;self.parent_fd=-1;self.db_fd=-1
    def _cleanup(self):
        for field in ("db_fd","parent_fd"):
            fd=getattr(self,field,-1)
            if fd>=0:
                try:os.close(fd)
                except OSError:pass
            setattr(self,field,-1)
    def __enter__(self):
        require_linux_loader_primitives()
        try:
            self.parent_fd,self.name=_open_parent(self.path,set(self.approved));self.parent_identity=_file_identity(os.fstat(self.parent_fd))
            self.db_fd=os.open(self.name,os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=self.parent_fd)
            self.db_identity=_file_identity(os.fstat(self.db_fd));self._validate_db();self._validate_sidecars();return self
        except OSError as e:
            self._cleanup();raise RuntimeError("database_file_open_failed") from e
        except Exception:
            self._cleanup();raise
    def _validate_db(self):
        fdst=os.fstat(self.db_fd)
        try:pathst=_stat_at(self.parent_fd,self.name)
        except OSError as e:raise RuntimeError("database_path_changed") from e
        if _file_identity(fdst)!=self.db_identity or _file_identity(fdst)!=_file_identity(pathst) or _file_identity(os.fstat(self.parent_fd))!=self.parent_identity:raise RuntimeError("database_path_changed")
        _validate_regular(fdst,self.uid,0o600,"database_file_policy_invalid",max_bytes=self.max_bytes)
    def _validate_sidecars(self):
        for suffix in self.SIDECARS:
            name=self.name+suffix
            try:st=_stat_at(self.parent_fd,name)
            except FileNotFoundError:continue
            _validate_regular(st,self.uid,0o600,"database_sidecar_policy_invalid",max_bytes=self.max_bytes)
            fd=os.open(name,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=self.parent_fd)
            try:
                if _file_identity(os.fstat(fd))!=_file_identity(_stat_at(self.parent_fd,name)):raise RuntimeError("database_sidecar_changed")
            finally:os.close(fd)
    def validate(self,stage):self._validate_db();self._validate_sidecars()
    def __exit__(self,*exc):self._cleanup()

class _BrokerCursor:
    """Minimal result facade: never expose sqlite's raw cursor or connection."""
    __slots__=("__cursor","__connection")
    def __init__(self,cursor,connection):self.__cursor=cursor;self.__connection=connection
    def _fetch(self,method,*args):
        self.__connection._before()
        try:return getattr(self.__cursor,method)(*args)
        finally:self.__connection._after()
    def fetchone(self):return self._fetch("fetchone")
    def fetchall(self):return self._fetch("fetchall")
    def fetchmany(self,size=None):return self._fetch("fetchmany",*(() if size is None else (size,)))
    def __iter__(self):return self
    def __next__(self):
        row=self.fetchone()
        if row is None:raise StopIteration
        return row
    @property
    def rowcount(self):self.__connection._before();value=self.__cursor.rowcount;self.__connection._after();return value
    @property
    def lastrowid(self):self.__connection._before();value=self.__cursor.lastrowid;self.__connection._after();return value

class _BrokerConnection:
    def __init__(self,broker):self._broker=broker;self._db=None;self._locked=False;self._owner=None
    def __enter__(self):
        if self._db is not None or self._locked:raise RuntimeError("database_connection_reused")
        owner=threading.get_ident()
        if self._broker._active_owner==owner:raise RuntimeError("database_nested_connection_prohibited")
        if not self._broker._connection_lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS):raise RuntimeError("database_broker_busy")
        self._locked=True
        try:
            if self._broker._closed:raise RuntimeError("database_broker_closed")
            if self._broker._active_connection is not None:raise RuntimeError("database_nested_connection_prohibited")
            db=self._broker._open_connection()
            self._db=db;self._owner=owner;self._broker._active_connection=self;self._broker._active_owner=owner
            return self
        except Exception:
            if self._broker._active_connection is self:
                self._broker._active_connection=None;self._broker._active_owner=None
            self._db=None;self._owner=None;self._locked=False;self._broker._connection_lock.release();raise
    def __exit__(self,kind,value,tb):
        db=self._db
        try:
            try:
                if db is not None:
                    self._before()
                    if kind is None:db.commit()
                    else:db.rollback()
                    self._after()
            finally:
                if db is not None:
                    try:self._broker._verify_connection_invariants(db)
                    finally:
                        db.close();self._broker._authorizers.pop(id(db),None)
                self._broker._postflight()
        finally:
            self._db=None;self._owner=None
            if self._broker._active_connection is self:
                self._broker._active_connection=None;self._broker._active_owner=None
            if self._locked:self._locked=False;self._broker._connection_lock.release()
        return False
    def _before(self):
        if self._db is None:raise RuntimeError("database_connection_not_entered")
        self._broker._validate_custody(allow_journal=self._db.in_transaction);self._broker._verify_connection_invariants(self._db)
    def _after(self):
        self._broker._verify_connection_invariants(self._db);self._broker._validate_custody(allow_journal=self._db.in_transaction)
    def execute(self,*a,**k):
        self._before()
        try:
            if a and _top_level_keyword(a[0])=="VACUUM":raise sqlite3.DatabaseError("not authorized")
            return _BrokerCursor(self._db.execute(*a,**k),self)
        finally:self._after()
    def bootstrap_authority_schema(self,script):
        """Execute the one identity-bound internal schema constant, never an application script."""
        self._before()
        try:
            if script is not AUTHORITY_SCHEMA_SCRIPT or self._db.in_transaction:raise RuntimeError("database_schema_script_invalid")
            return _BrokerCursor(self._db.executescript(script),self)
        finally:self._after()
    def authority_table_columns(self,table):
        if table not in {"activation_challenges","external_entitlements","external_revocations"}:raise RuntimeError("database_schema_introspection_invalid")
        self._before();setup=self._broker._authorizers[id(self._db)][1]
        try:
            setup["introspection"]=("table_info",table)
            return {row[1] for row in self._db.execute(f"PRAGMA table_info({table})")}
        finally:
            setup["introspection"]=None;self._after()
    def executemany(self,*a,**k):
        self._before()
        try:return _BrokerCursor(self._db.executemany(*a,**k),self)
        finally:self._after()
    def commit(self):
        self._before()
        try:self._db.commit()
        finally:self._after()
    def rollback(self):
        self._before()
        try:self._db.rollback()
        finally:self._after()

class ProductionSQLiteBroker(AuthorityDatabaseBroker):
    """Process-lifetime custody of one pre-provisioned SQLite DB in a private directory.

    DELETE journaling is intentional: stale journals are rejected, never removed. This controls
    local pathname/sidecar lifecycle but does not defend against root, same-UID process compromise,
    or hostile mount/FUSE/overlay semantics; those remain exact-host gates.
    """
    DATABASE_NAME="authority.sqlite3";LOCK_NAME=".authority-db.custody.lock";fixture=False
    def __init__(self,path:Path,expected_uid:int,approved_directory_uids):
        require_linux_loader_primitives();self.path=_absolute(str(path),"database_path");self.uid=expected_uid;self.approved=frozenset(approved_directory_uids);self.parent_fd=self.dir_fd=self.db_fd=self.lock_fd=-1;self._closed=False;self._connection_lock=threading.RLock();self._active_connection=None;self._active_owner=None;self._authorizers={}
        if self.path.name!=self.DATABASE_NAME:raise RuntimeError("database_basename_invalid")
        try:
            self.parent_fd,self.dir_name=_open_parent(self.path.parent,set(self.approved));self.parent_identity=_file_identity(os.fstat(self.parent_fd))
            self.dir_fd=os.open(self.dir_name,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|os.O_NOFOLLOW,dir_fd=self.parent_fd)
            dst=os.fstat(self.dir_fd)
            if not stat.S_ISDIR(dst.st_mode) or dst.st_uid!=self.uid or stat.S_IMODE(dst.st_mode)!=0o700:raise RuntimeError("database_directory_policy_invalid")
            self.dir_identity=_file_identity(dst);self.name=self.DATABASE_NAME
            self.lock_fd=os.open(self.LOCK_NAME,os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW,dir_fd=self.dir_fd);lst=os.fstat(self.lock_fd);_validate_regular(lst,self.uid,0o600,"database_lock_policy_invalid",max_bytes=4096)
            self.lock_identity=_file_identity(lst)
            try:fcntl.flock(self.lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as e:raise RuntimeError("database_custody_lock_contended") from e
            self.db_fd=os.open(self.name,os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=self.dir_fd);dbst=os.fstat(self.db_fd);_validate_regular(dbst,self.uid,0o600,"database_file_policy_invalid",max_bytes=16*1024**3);self.db_identity=_file_identity(dbst)
            self._validate_custody(allow_journal=False)
        except Exception:
            self.close();raise
    @property
    def identity(self):return ("production-sqlite-delete-v1",str(self.path),self.dir_identity,self.db_identity,self.lock_identity) if not self._closed else None
    def _entry(self,name):return _file_identity(_stat_at(self.dir_fd,name))
    def _validate_custody(self,*,allow_journal):
        if self._closed or min(self.dir_fd,self.db_fd,self.lock_fd)<0:raise RuntimeError("database_broker_closed")
        try:configured_dir=_file_identity(_stat_at(self.parent_fd,self.dir_name))
        except OSError as e:raise RuntimeError("database_custody_identity_changed") from e
        if (_file_identity(os.fstat(self.parent_fd))!=self.parent_identity or configured_dir!=self.dir_identity
                or _file_identity(os.fstat(self.dir_fd))!=self.dir_identity or _file_identity(os.fstat(self.db_fd))!=self.db_identity
                or self._entry(self.name)!=self.db_identity or _file_identity(os.fstat(self.lock_fd))!=self.lock_identity
                or self._entry(self.LOCK_NAME)!=self.lock_identity):raise RuntimeError("database_custody_identity_changed")
        allowed={self.name,self.LOCK_NAME};journal=self.name+"-journal"
        if allow_journal:allowed.add(journal)
        try:entries=set(os.listdir(self.dir_fd))
        except OSError as e:raise RuntimeError("database_directory_unavailable") from e
        if not entries<=allowed:raise RuntimeError("database_directory_entry_unapproved")
        if journal in entries:
            st=_stat_at(self.dir_fd,journal);_validate_regular(st,self.uid,0o600,"database_journal_policy_invalid",max_bytes=16*1024**3)
            fd=os.open(journal,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=self.dir_fd)
            try:
                if _file_identity(os.fstat(fd))!=_file_identity(_stat_at(self.dir_fd,journal)):raise RuntimeError("database_journal_changed")
            finally:os.close(fd)
    def _verify_database_list(self,db):
        try:targets=db.execute("PRAGMA database_list").fetchall()
        except Exception as e:raise RuntimeError("database_connection_target_invalid") from e
        if len(targets)!=1 or targets[0][1]!="main":raise RuntimeError("database_connection_target_invalid")
        try:target_identity=_file_identity(os.stat(targets[0][2],follow_symlinks=True))
        except OSError as e:raise RuntimeError("database_connection_target_invalid") from e
        if target_identity!=self.db_identity:raise RuntimeError("database_connection_target_invalid")
    def _verify_connection_invariants(self,db):
        self._verify_database_list(db)
        expected={
            "journal_mode":"delete","synchronous":2,"temp_store":2,"foreign_keys":1,
            "trusted_schema":0,"locking_mode":"normal","query_only":0,"secure_delete":1,
            "busy_timeout":30000,
        }
        try:
            actual={name:db.execute(f"PRAGMA {name}").fetchone()[0] for name in expected}
        except Exception as e:raise RuntimeError("database_connection_invariant_invalid") from e
        for name,value in actual.items():
            wanted=expected[name]
            if isinstance(wanted,str):value=str(value).lower()
            if value!=wanted:raise RuntimeError("database_connection_invariant_invalid")
    def _open_connection(self):
        self._validate_custody(allow_journal=False)
        uri=f"file:/proc/self/fd/{self.dir_fd}/{quote(self.name,safe='')}?mode=rw"
        db=_SQLITE_CONNECT(uri,uri=True,timeout=30,isolation_level=None);setup={"active":True,"introspection":None}
        def authorizer(action,arg1,arg2,database,trigger):
            try:
                if action in (sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH):return sqlite3.SQLITE_DENY
                if action==sqlite3.SQLITE_PRAGMA:
                    name=str(arg1 or "").lower();argument=None if arg2 is None or str(arg2)=="" else str(arg2).lower()
                    if setup["active"]:
                        if argument is None:return sqlite3.SQLITE_OK
                        return sqlite3.SQLITE_OK if (name,argument) in _SETUP_PRAGMA_WRITES else sqlite3.SQLITE_DENY
                    if argument is None and name in _READ_ONLY_PRAGMAS:return sqlite3.SQLITE_OK
                    if setup["introspection"]==(name,str(arg2)):return sqlite3.SQLITE_OK
                    return sqlite3.SQLITE_DENY
                if hasattr(sqlite3,"SQLITE_FUNCTION") and action==sqlite3.SQLITE_FUNCTION and str(arg2 or arg1).lower()=="load_extension":return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            except Exception:return sqlite3.SQLITE_DENY
        try:
            db.set_authorizer(authorizer);self._authorizers[id(db)]=(authorizer,setup);db.row_factory=sqlite3.Row
            if db.execute("PRAGMA journal_mode=DELETE").fetchone()[0].lower()!="delete":raise RuntimeError("database_journal_mode_invalid")
            db.execute("PRAGMA foreign_keys=ON");db.execute("PRAGMA busy_timeout=30000");db.execute("PRAGMA synchronous=FULL");db.execute("PRAGMA temp_store=MEMORY");db.execute("PRAGMA trusted_schema=OFF");db.execute("PRAGMA locking_mode=NORMAL");db.execute("PRAGMA query_only=OFF");db.execute("PRAGMA secure_delete=ON")
            setup["active"]=False;self._verify_connection_invariants(db)
            self._validate_custody(allow_journal=False);return db
        except Exception:
            self._authorizers.pop(id(db),None);db.close();self._postflight();raise
    def _postflight(self):self._validate_custody(allow_journal=False)
    def connect(self):
        if type(self) is not ProductionSQLiteBroker or self.identity is None:raise RuntimeError("production_database_broker_invalid")
        return _BrokerConnection(self)
    def close(self):
        if not self._connection_lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS):raise RuntimeError("database_broker_busy")
        try:
            if self._active_connection is not None:raise RuntimeError("database_broker_connection_active")
            if self._closed:return
            for field in ("db_fd","lock_fd","dir_fd","parent_fd"):
                fd=getattr(self,field,-1)
                if fd>=0:
                    try:os.close(fd)
                    except OSError:pass
                setattr(self,field,-1)
            self._closed=True;self._authorizers.clear()
        finally:self._connection_lock.release()
    def __del__(self):
        try:self.close()
        except Exception:pass

def validate_production_database(path,uid,approved):
    return TrustedDatabaseGuard(_absolute(str(path),"database_path"),uid,frozenset(approved))

class LocalV1PersistentAnchor:
    """Pre-provisioned local CAS; requires exact-host external-witness drill."""
    production_safe=True;fixture=False;process_local=False
    def __init__(self,path:Path,expected_uid:int,approved_directory_uids=None):
        self.path=path;self.uid=expected_uid;self.approved=frozenset(approved_directory_uids or {0,expected_uid})
    def _open_dir(self):
        fd,name=_open_parent(self.path,set(self.approved));return fd,name,_file_identity(os.fstat(fd))
    def _open_lock(self,dfd,name,parent_id):
        fd=os.open(name+".lock",os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW,dir_fd=dfd);st=os.fstat(fd);_validate_regular(st,self.uid,0o600,"anchor_lock_policy_invalid")
        if _file_identity(st)!=_file_identity(_stat_at(dfd,name+".lock")) or _file_identity(os.fstat(dfd))!=parent_id:os.close(fd);raise RuntimeError("anchor_lock_changed")
        return fd
    def _read_locked(self,dfd,name,parent_id):
        fd=os.open(name,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dfd)
        try:
            a=os.fstat(fd);_validate_regular(a,self.uid,0o400,"anchor_invalid",max_bytes=4096,allow_empty=False);data=_read_all(fd,4096);b=os.fstat(fd)
            if len(data)!=a.st_size or not _stable(a,b) or _file_identity(b)!=_file_identity(_stat_at(dfd,name)) or _file_identity(os.fstat(dfd))!=parent_id:raise RuntimeError("anchor_changed")
            return validate_anchor_claim(_json(data,{"generation","ceremony_sha256"},"anchor_invalid"))
        finally:os.close(fd)
    def read(self):
        dfd,name,parent=self._open_dir()
        try:
            lock=self._open_lock(dfd,name,parent)
            try:
                fcntl.flock(lock,fcntl.LOCK_SH)
                if _file_identity(os.fstat(lock))!=_file_identity(_stat_at(dfd,name+".lock")):raise RuntimeError("anchor_lock_changed")
                result=self._read_locked(dfd,name,parent)
                if _file_identity(os.fstat(lock))!=_file_identity(_stat_at(dfd,name+".lock")) or _file_identity(os.fstat(dfd))!=parent:raise RuntimeError("anchor_lock_changed")
                return result
            finally:os.close(lock)
        finally:os.close(dfd)
    def compare_and_advance(self,expected,new):
        expected=validate_anchor_claim(expected);new=validate_anchor_claim(new,allow_zero=False);dfd,name,parent=self._open_dir();temp=None
        try:
            lock=self._open_lock(dfd,name,parent)
            try:
                fcntl.flock(lock,fcntl.LOCK_EX)
                if _file_identity(os.fstat(lock))!=_file_identity(_stat_at(dfd,name+".lock")):raise RuntimeError("anchor_lock_changed")
                current=self._read_locked(dfd,name,parent)
                if current==new:
                    result=current
                    if _file_identity(os.fstat(lock))!=_file_identity(_stat_at(dfd,name+".lock")) or _file_identity(os.fstat(dfd))!=parent:raise RuntimeError("anchor_lock_changed")
                    return result
                if current!=expected or new["generation"]!=expected["generation"]+1:raise RuntimeError("anchor_conflict")
                # Random names make stale files harmless; only this invocation's name is cleaned.
                temp=f".{name}.new.{os.getpid()}.{secrets.token_hex(8)}";fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|os.O_NOFOLLOW,0o400,dir_fd=dfd)
                try:
                    payload=canonical(new);offset=0
                    while offset<len(payload):
                        written=os.write(fd,payload[offset:])
                        if written<=0:raise RuntimeError("anchor_write_failed")
                        offset+=written
                    st=os.fstat(fd);_validate_regular(st,self.uid,0o400,"anchor_temp_policy_invalid",max_bytes=4096,allow_empty=False);os.fsync(fd)
                    if _file_identity(st)!=_file_identity(_stat_at(dfd,temp)):raise RuntimeError("anchor_temp_changed")
                finally:os.close(fd)
                if _file_identity(os.fstat(dfd))!=parent:raise RuntimeError("anchor_parent_changed")
                os.rename(temp,name,src_dir_fd=dfd,dst_dir_fd=dfd);temp=None;os.fsync(dfd)
                if _file_identity(os.fstat(dfd))!=parent:raise RuntimeError("anchor_parent_changed")
                result=self._read_locked(dfd,name,parent)
                if _file_identity(os.fstat(lock))!=_file_identity(_stat_at(dfd,name+".lock")) or _file_identity(os.fstat(dfd))!=parent:raise RuntimeError("anchor_lock_changed")
                return result
            finally:os.close(lock)
        finally:
            if temp is not None:
                try:os.unlink(temp,dir_fd=dfd)
                except FileNotFoundError:pass
            os.close(dfd)

def load_production_config(config_path:Path|str, *, expected_uid:int):
    if type(expected_uid) is not int or expected_uid <= 0:raise RuntimeError("expected_service_uid_invalid")
    path=_absolute(str(config_path),"fixed_config")
    if path.name != "authority-production.json" or str(path)!=os.path.normpath(str(path)) or "//" in str(path):raise RuntimeError("fixed_config_path_invalid")
    cfg=_json(_read_fixed(path,expected_uid=expected_uid,approved_directory_uids=frozenset({0,expected_uid})),CONFIG_FIELDS,"fixed_config_invalid")
    if cfg["schema_version"]!=1 or type(cfg["expected_uid"]) is not int or cfg["expected_uid"] != expected_uid:raise RuntimeError("fixed_config_uid_binding_mismatch")
    if type(cfg["approved_directory_uids"]) is not list or cfg["expected_uid"] not in cfg["approved_directory_uids"] or 0 not in cfg["approved_directory_uids"] or any(type(x) is not int or x<0 for x in cfg["approved_directory_uids"]):raise RuntimeError("fixed_config_invalid")
    if type(cfg["anchor"]) is not dict or set(cfg["anchor"])!=ANCHOR_FIELDS or cfg["anchor"]["provider"]!="local-v1" or cfg["anchor"]["expected_uid"]!=cfg["expected_uid"]:raise RuntimeError("fixed_config_invalid")
    if type(cfg["listen"]) is not dict or set(cfg["listen"])!=LISTEN_FIELDS or cfg["listen"]["host"] not in {"127.0.0.1","::1"} or type(cfg["listen"]["port"]) is not int or not 1024<=cfg["listen"]["port"]<=65535:raise RuntimeError("fixed_config_invalid")
    for k in ("private_key_path","database_path","reviewed_public_key_path","descriptor_path","ceremony_record_path"):_absolute(cfg[k],k)
    _absolute(cfg["anchor"]["path"],"anchor_path");return cfg

def build_production_authority(config_path:Path|str,*,expected_uid:int,anchor_factory:Callable[[dict],Any]|None=None,broker_factory=None):
    cfg=load_production_config(config_path,expected_uid=expected_uid);uid=cfg["expected_uid"];public=_read_fixed(Path(cfg["reviewed_public_key_path"]),expected_uid=uid)
    if hashlib.sha256(public).hexdigest()!=cfg["reviewed_public_key_sha256"]:raise RuntimeError("reviewed_public_key_digest_mismatch")
    descriptor=_loads(_read_fixed(Path(cfg["descriptor_path"]),expected_uid=uid),"descriptor_invalid");record=_loads(_read_fixed(Path(cfg["ceremony_record_path"]),expected_uid=uid),"ceremony_record_invalid")
    if type(descriptor) is not dict or descriptor.get("release_sha256")!=cfg["release_sha256"] or descriptor.get("deployment_config_sha256")!=cfg["deployment_config_sha256"]:raise RuntimeError("fixed_config_descriptor_mismatch")
    anchor=(anchor_factory or (lambda a:LocalV1PersistentAnchor(Path(a["path"]),a["expected_uid"],cfg["approved_directory_uids"])))(cfg["anchor"])
    if isinstance(anchor,OfflineFixtureMonotonicAnchor) or getattr(anchor,"production_safe",False) is not True or getattr(anchor,"fixture",False) or getattr(anchor,"process_local",False):raise RuntimeError("production_anchor_unsafe")
    # Programmatic factory exists only for deterministic tests. The CLI always constructs the
    # concrete sealed broker from fixed config and never accepts env/request/provider injection.
    broker=(broker_factory or ProductionSQLiteBroker)(Path(cfg["database_path"]),uid,frozenset(cfg["approved_directory_uids"]))
    if type(broker) is not ProductionSQLiteBroker or broker.fixture or broker.identity is None:raise RuntimeError("production_database_broker_invalid")
    try:
        authority=LicenseAuthority.from_hardened_pem(database_broker=broker,private_key_file=Path(cfg["private_key_path"]),expected_uid=uid,approved_directory_uids=frozenset(cfg["approved_directory_uids"]),signer_descriptor=descriptor,ceremony_record=record,reviewed_public_key=public,authorized_reviewers=cfg["authorized_reviewers"],generation_anchor=anchor,authority_id=cfg["authority_id"])
    except Exception:
        broker.close();raise
    if type(authority) is not LicenseAuthority or authority._database_broker is not broker:broker.close();raise RuntimeError("production_database_broker_binding_failed")
    authority._production_config=cfg;return authority

build_production_authority.production_safe = True
build_production_authority.fixture = False
build_production_authority.process_local = False


def main(argv=None,*,server_runner=None,app_factory=None):
    """Delegate every runnable production path to the reviewed closed composition."""
    # Alternate factories (including wrappers and functools.partial) are not a production
    # extension point. Reject before argv parsing, provider construction, filesystem access,
    # or server/socket work.
    if app_factory is not None:
        raise RuntimeError("production_alternate_app_factory_forbidden")
    from .authority_composition import run as composition_run
    return composition_run(argv,server_runner=server_runner)
def cli_main():
    """Run only the closed fixed-config production composition candidate."""
    from .authority_composition import cli_main as composition_cli_main
    return composition_cli_main()
if __name__=="__main__":cli_main()
