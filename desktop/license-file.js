'use strict';
const fs=require('node:fs'),path=require('node:path');
function samePath(left,right,isWindows){const normalize=value=>path.resolve(value).replaceAll('\\','/');const a=normalize(left),b=normalize(right);return isWindows?a.toLowerCase()===b.toLowerCase():a===b;}
function readStableRegularFile(file,{maxBytes=65536,fsImpl=fs}={}){
 const hasNoFollow=Number.isInteger(fs.constants.O_NOFOLLOW)&&fs.constants.O_NOFOLLOW!==0,isWindows=process.platform==='win32';
 // Windows has no O_NOFOLLOW and reports nlink=0 for ordinary files on some
 // filesystems. Resolve and compare the path before open, then compare the
 // opened handle to a fresh path stat. Payload authenticity/confidentiality
 // remains enforced by the signed license or safeStorage-encrypted container.
 if(!hasNoFollow){const before=fsImpl.lstatSync(file);if(before.isSymbolicLink()||!before.isFile()||(!isWindows&&before.nlink!==1))throw Error('unsafe file');const real=fsImpl.realpathSync.native?fsImpl.realpathSync.native(file):fsImpl.realpathSync(file);if(!samePath(real,file,isWindows))throw Error('unsafe file');}
 const fd=fsImpl.openSync(file,fs.constants.O_RDONLY|(hasNoFollow?fs.constants.O_NOFOLLOW:0));try{const st=fsImpl.fstatSync(fd);if(!st.isFile()||(!isWindows&&st.nlink!==1)||st.size<0||st.size>maxBytes)throw Error('unsafe file');const data=Buffer.alloc(st.size);let offset=0;while(offset<st.size){const count=fsImpl.readSync(fd,data,offset,st.size-offset,offset);if(count<=0)throw Error('short read');offset+=count;}const after=fsImpl.fstatSync(fd),linked=fsImpl.lstatSync(file);if(data.length!==st.size||after.dev!==st.dev||after.ino!==st.ino||after.size!==st.size||(!isWindows&&after.nlink!==1)||!linked.isFile()||linked.isSymbolicLink()||linked.dev!==after.dev||linked.ino!==after.ino||linked.size!==after.size||(!isWindows&&linked.nlink!==1))throw Error('unstable file');return data;}finally{fsImpl.closeSync(fd);}}
module.exports={readStableRegularFile,samePath};
