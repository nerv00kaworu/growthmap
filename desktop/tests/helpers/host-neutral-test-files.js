'use strict';
// Test-only durable files adapter. It enforces path/identity/size invariants without
// pretending that Windows exposes POSIX uid/mode security semantics.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const NAME=/^[A-Za-z0-9-]{1,80}\.(?:bin|recover)$/;
const identity=s=>{if(!Number.isInteger(s.dev)||!Number.isInteger(s.ino)||(s.dev===0&&s.ino===0))throw Error('Test identity unavailable');return `${s.dev}:${s.ino}`};
const WINDOWS_DIR_FSYNC_UNSUPPORTED=new Set(['EPERM','EISDIR','EINVAL','ENOTSUP','EOPNOTSUPP']);
function createHostNeutralTestFiles(trustedRoot,directory=trustedRoot,{io=fs,hooks={},maxReadBytes=1024*1024,platform=process.platform}={}){
 trustedRoot=path.resolve(trustedRoot);directory=path.resolve(directory);
 const relative=path.relative(trustedRoot,directory);
 if(relative==='..'||relative.startsWith(`..${path.sep}`)||path.isAbsolute(relative))throw Error('Test files directory escapes trusted root');
 const check=(p,kind='dir')=>{const s=io.lstatSync(p);if(s.isSymbolicLink()||(kind==='dir'?!s.isDirectory():!s.isFile()))throw Error(`Unsafe test ${kind}`);if(kind==='file'&&Number.isSafeInteger(s.nlink)&&s.nlink!==1)throw Error('Unsafe test hardlink');return s};
 const verifyDir=()=>{if(!io.existsSync(trustedRoot))io.mkdirSync(trustedRoot,{recursive:false});let current=trustedRoot;check(current);for(const part of relative.split(path.sep).filter(Boolean)){const before=check(current);current=path.join(current,part);if(!io.existsSync(current)){hooks.beforeMkdir?.(current);io.mkdirSync(current);hooks.afterMkdir?.(current)}check(current);if(identity(before)!==identity(check(path.dirname(current))))throw Error('Test parent replaced')}const rr=io.realpathSync(trustedRoot),rd=io.realpathSync(directory),r=path.relative(rr,rd);if(r==='..'||r.startsWith(`..${path.sep}`)||path.isAbsolute(r))throw Error('Test files directory escapes trusted root');return check(directory)};
 const safe=name=>{if(!NAME.test(name))throw Error('Unsafe test filename');return path.join(directory,name)};
 const stable=(before,hook)=>{hooks[hook]?.(directory);if(identity(before)!==identity(verifyDir()))throw Error('Test parent replaced')};
 const read=name=>{const parent=verifyDir(),target=safe(name),flags=io.constants.O_RDONLY|(io.constants.O_NOFOLLOW||0),fd=io.openSync(target,flags);try{const before=io.fstatSync(fd);if(before.isSymbolicLink()||!before.isFile()||(Number.isSafeInteger(before.nlink)&&before.nlink!==1))throw Error('Unsafe test file');if(before.size<0||before.size>maxReadBytes)throw Error('Test file is too large');hooks.beforeRead?.(target,fd);const data=io.readFileSync(fd),after=io.fstatSync(fd);if(data.length>maxReadBytes)throw Error('Test file is too large');if(identity(before)!==identity(after)||before.size!==after.size||before.mtimeMs!==after.mtimeMs)throw Error('Unstable test file');stable(parent,'beforeReadReturn');return data}finally{io.closeSync(fd)}};
 const syncDir=()=>{const parent=verifyDir();let fd;try{fd=io.openSync(directory,'r')}catch(e){if(platform!=='win32'||!WINDOWS_DIR_FSYNC_UNSUPPORTED.has(e.code))throw e;stable(parent,'afterDirSync');return}try{try{io.fsyncSync(fd)}catch(e){if(platform!=='win32'||!WINDOWS_DIR_FSYNC_UNSUPPORTED.has(e.code))throw e}}finally{io.closeSync(fd)}stable(parent,'afterDirSync')};
 const write=(name,data)=>{const parent=verifyDir(),target=safe(name),tmp=`${target}.tmp-${process.pid}-${crypto.randomBytes(8).toString('hex')}`,fd=io.openSync(tmp,io.constants.O_CREAT|io.constants.O_EXCL|io.constants.O_WRONLY,0o600);try{io.writeFileSync(fd,data);io.fsyncSync(fd)}finally{io.closeSync(fd)}try{stable(parent,'beforeRename');check(tmp,'file');io.renameSync(tmp,target);stable(parent,'afterRename');check(target,'file');syncDir()}catch(e){try{io.unlinkSync(tmp)}catch{}throw e}};
 const remove=name=>{const parent=verifyDir(),target=safe(name);try{read(name)}catch(e){if(e.code==='ENOENT')return;throw e}stable(parent,'beforeUnlink');io.unlinkSync(target);stable(parent,'afterUnlink');syncDir()};
 return {verifyDir,read,write,remove,exists:name=>{verifyDir();try{read(name);return true}catch(e){if(e.code==='ENOENT')return false;throw e}},quarantine:remove,list:()=>{verifyDir();return io.readdirSync(directory)}};
}
function createHostNeutralTestFilesFactory(options={}){return (trustedRoot,directory,extra={})=>createHostNeutralTestFiles(trustedRoot,directory,{...options,...extra,hooks:{...(options.hooks||{}),...(extra.hooks||{})}})}
module.exports={createHostNeutralTestFiles,createHostNeutralTestFilesFactory};
