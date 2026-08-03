'use strict';
const fs=require('node:fs'),path=require('node:path');
function canonicalPath(value,isWindows){let raw=String(value).replaceAll('\\','/');if(isWindows){if(raw.toLowerCase().startsWith('//?/unc/'))raw=`//${raw.slice(8)}`;else if(raw.startsWith('//?/'))raw=raw.slice(4);return path.win32.resolve(raw).replaceAll('\\','/').toLowerCase();}return path.resolve(raw).replaceAll('\\','/');}
function samePath(left,right,isWindows){return canonicalPath(left,isWindows)===canonicalPath(right,isWindows);}
function windowsStable(opened,linked){const comparable=(a,b)=>Number.isFinite(a)&&Number.isFinite(b)&&a!==0&&b!==0;return opened.size===linked.size&&opened.mtimeMs===linked.mtimeMs&&opened.birthtimeMs===linked.birthtimeMs&&(!comparable(opened.dev,linked.dev)||opened.dev===linked.dev)&&(!comparable(opened.ino,linked.ino)||opened.ino===linked.ino);}
function readStableRegularFile(file,{maxBytes=65536,fsImpl=fs}={}){
 const isWindows=process.platform==='win32',hasNoFollow=!isWindows&&Number.isInteger(fs.constants.O_NOFOLLOW)&&fs.constants.O_NOFOLLOW!==0;
 // Windows has no reliable O_NOFOLLOW and runner temp paths may traverse a
 // stable junction/alias. Reject a symlink final component, pin the canonical
 // target before open, then require that same target and stable metadata after
 // reading from one handle. Signed/encrypted payloads remain authenticated.
 let initialReal=null;
 if(!hasNoFollow){const before=fsImpl.lstatSync(file);if(before.isSymbolicLink()||!before.isFile()||(!isWindows&&before.nlink!==1))throw Error('unsafe file');initialReal=fsImpl.realpathSync.native?fsImpl.realpathSync.native(file):fsImpl.realpathSync(file);if(!isWindows&&!samePath(initialReal,file,false))throw Error('unsafe file');}
 const fd=fsImpl.openSync(file,fs.constants.O_RDONLY|(hasNoFollow?fs.constants.O_NOFOLLOW:0));try{const st=fsImpl.fstatSync(fd);if(!st.isFile()||(!isWindows&&st.nlink!==1)||st.size<0||st.size>maxBytes)throw Error('unsafe file');const data=Buffer.alloc(st.size);let offset=0;while(offset<st.size){const count=fsImpl.readSync(fd,data,offset,st.size-offset,offset);if(count<=0)throw Error('short read');offset+=count;}const after=fsImpl.fstatSync(fd),linked=fsImpl.lstatSync(file),real=fsImpl.realpathSync.native?fsImpl.realpathSync.native(file):fsImpl.realpathSync(file);const stable=isWindows?windowsStable(after,linked):(after.dev===st.dev&&after.ino===st.ino&&after.size===st.size&&after.nlink===1&&linked.dev===after.dev&&linked.ino===after.ino&&linked.size===after.size&&linked.nlink===1);if(data.length!==st.size||!linked.isFile()||linked.isSymbolicLink()||(initialReal!==null&&!samePath(real,initialReal,isWindows))||!stable)throw Error('unstable file');return data;}finally{fsImpl.closeSync(fd);}}
module.exports={readStableRegularFile,samePath,windowsStable,canonicalPath};
