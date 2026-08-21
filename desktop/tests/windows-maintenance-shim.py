import sys,os,json,sqlite3,hashlib,shutil
flag,source=sys.argv[1:3]
def meta(p,source_meta=None):
 b=open(p,'rb').read(); s=os.stat(p)
 with sqlite3.connect(p) as c:
  if c.execute('pragma integrity_check').fetchone()[0]!='ok': raise ValueError('integrity')
  tables={r[0] for r in c.execute("select name from sqlite_master where type='table'")}
  projects=c.execute('select count(*) from projects').fetchone()[0] if 'projects' in tables else 0
  active=c.execute("select count(*) from projects where status='active'").fetchone()[0] if 'projects' in tables else 0
 r={'sha256':hashlib.sha256(b).hexdigest(),'size':len(b),'device':str(s.st_dev),'inode':str(s.st_ino),'counts':{'projects':projects,'activeProjects':active},'durability':{'fileFlush':'FlushFileBuffers','directoryFlush':'unsupported-windows-best-effort'}}
 if source_meta:r.update(sourceSha256=source_meta['sha256'],sourceSize=source_meta['size'])
 return r
if flag in ('--validate-db','--stable-validate-db'):
 print(json.dumps(meta(source)))
elif flag=='--validated-snapshot-db':
 before=meta(source); dest=os.environ['GROWTHMAP_MAINTENANCE_DESTINATION']
 if os.path.exists(dest): raise ValueError('target')
 src=sqlite3.connect(source); out=sqlite3.connect(dest)
 try: src.backup(out); out.commit()
 finally: out.close(); src.close()
 with open(dest,'rb+') as f: os.fsync(f.fileno())
 print(json.dumps(meta(dest,before)))
else: raise ValueError('unsupported (shim never installs/renames)')
