"""Dependency-free SQLite authority concurrency and rollback matrix."""
import hashlib, sqlite3, subprocess, sys, tempfile, time, unittest
from pathlib import Path
MAX=9007199254740991
SCHEMA="""PRAGMA foreign_keys=ON;PRAGMA user_version=12;
CREATE TABLE provider_configs(id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,secret_change_pending INTEGER NOT NULL);
INSERT INTO provider_configs VALUES('a',1,0),('b',1,0);
CREATE TABLE provider_selection(singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),provider_id TEXT REFERENCES provider_configs(id) ON DELETE SET NULL,selection_revision INTEGER NOT NULL DEFAULT 1 CHECK(selection_revision BETWEEN 1 AND 9007199254740991),updated_at TEXT NOT NULL);
INSERT INTO provider_selection VALUES(1,'a',1,CURRENT_TIMESTAMP);"""
WORKER=r'''import sqlite3,sys,time
p,op,target=sys.argv[1:4]
for attempt in range(8):
 try:
  c=sqlite3.connect(p,timeout=.04,isolation_level=None);c.execute('PRAGMA foreign_keys=ON');c.execute('BEGIN IMMEDIATE')
  rev=1
  if op=='select':
   n=c.execute("UPDATE provider_selection SET provider_id=?,selection_revision=selection_revision+1 WHERE singleton_id=1 AND selection_revision=? AND selection_revision<9007199254740991 AND EXISTS(SELECT 1 FROM provider_configs WHERE id=? AND enabled=1 AND secret_change_pending=0)",(target,rev,target)).rowcount
  else:
   verb='UPDATE provider_configs SET enabled=0 WHERE id=?' if op=='disable' else 'DELETE FROM provider_configs WHERE id=?'
   c.execute(verb,(target,));n=c.execute('UPDATE provider_selection SET provider_id=NULL,selection_revision=selection_revision+1 WHERE singleton_id=1 AND provider_id=? AND selection_revision=? AND selection_revision<9007199254740991',(target,rev)).rowcount
  c.commit();print('commit',n);break
 except sqlite3.OperationalError as e:
  try:c.rollback();c.close()
  except:pass
  if getattr(e,'sqlite_errorcode',0)&255 not in (5,6):raise
  time.sleep(.015*(attempt+1))
else: print('busy',0)
'''
def filehash(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def logical(c):return (c.execute('SELECT * FROM provider_configs ORDER BY id').fetchall(),c.execute('SELECT singleton_id,provider_id,selection_revision FROM provider_selection').fetchall())
class Matrix(unittest.TestCase):
 def db(self,journal='DELETE'):
  td=tempfile.TemporaryDirectory();p=str(Path(td.name)/'authority.db');c=sqlite3.connect(p);c.executescript(SCHEMA);actual=c.execute('PRAGMA journal_mode='+journal).fetchone()[0].upper();self.assertEqual(actual,journal);c.commit();c.close();return td,p
 def race(self,p,*ops):
  ps=[subprocess.Popen([sys.executable,'-c',WORKER,p,*op],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for op in ops]
  out=[]
  for proc in ps:
   stdout,stderr=proc.communicate(timeout=8);self.assertEqual(proc.returncode,0,stderr);out.append(stdout.strip())
  return out
 def test_select_select_exactly_one_cas_winner(self):
  for journal in ('WAL','DELETE'):
   td,p=self.db(journal);out=self.race(p,('select','b'),('select','b'));self.assertEqual(sum(x=='commit 1' for x in out),1);c=sqlite3.connect(p);self.assertEqual(c.execute('SELECT provider_id,selection_revision FROM provider_selection').fetchone(),('b',2));c.close();td.cleanup()
 def test_select_vs_disable_delete_legal_serial_orders_and_invariants(self):
  for journal in ('WAL','DELETE'):
   for op in ('disable','delete'):
    td,p=self.db(journal);out=self.race(p,('select','b'),(op,'a'));self.assertGreaterEqual(sum(x.startswith('commit') for x in out),1);c=sqlite3.connect(p);provider=c.execute("SELECT enabled FROM provider_configs WHERE id='a'").fetchone();selected,rev=c.execute('SELECT provider_id,selection_revision FROM provider_selection').fetchone();self.assertTrue(provider is None if op=='delete' else provider==(0,));self.assertIn(selected,(None,'b'));self.assertGreaterEqual(rev,2);self.assertTrue(selected is None or c.execute("SELECT 1 FROM provider_configs WHERE id=? AND enabled=1 AND secret_change_pending=0",(selected,)).fetchone() is not None);c.close();td.cleanup()
 def test_max_revision_operations_rollback_and_sentinel_hashes(self):
  td,p=self.db();c=sqlite3.connect(p);c.execute('UPDATE provider_selection SET selection_revision=?',(MAX,));c.commit();before=(filehash(p),logical(c));c.execute('BEGIN');self.assertEqual(c.execute('UPDATE provider_selection SET provider_id=NULL,selection_revision=selection_revision+1 WHERE selection_revision<?',(MAX,)).rowcount,0);c.rollback();self.assertEqual(logical(c),before[1]);c.close();self.assertEqual(filehash(p),before[0]);td.cleanup()
if __name__=='__main__':unittest.main()
