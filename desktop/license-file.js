'use strict';
const fs=require('node:fs'),path=require('node:path');
function readStableRegularFile(file,{maxBytes=65536,fsImpl=fs}={}){
 const hasNoFollow=Number.isInteger(fs.constants.O_NOFOLLOW)&&fs.constants.O_NOFOLLOW!==0;
 if(!hasNoFollow){const before=fsImpl.lstatSync(file);if(before.isSymbolicLink()||!before.isFile()||before.nlink!==1)throw Error('unsafe file');const real=fsImpl.realpathSync.native?fsImpl.realpathSync.native(file):fsImpl.realpathSync(file);if(path.resolve(real)!==path.resolve(file))throw Error('unsafe file');}
 const fd=fsImpl.openSync(file,fs.constants.O_RDONLY|(hasNoFollow?fs.constants.O_NOFOLLOW:0));try{const st=fsImpl.fstatSync(fd);if(!st.isFile()||st.nlink!==1||st.size<0||st.size>maxBytes)throw Error('unsafe file');const data=Buffer.alloc(st.size);let offset=0;while(offset<st.size){const count=fsImpl.readSync(fd,data,offset,st.size-offset,offset);if(count<=0)throw Error('short read');offset+=count;}const after=fsImpl.fstatSync(fd);if(data.length!==st.size||after.dev!==st.dev||after.ino!==st.ino||after.size!==st.size||after.nlink!==1)throw Error('unstable file');return data;}finally{fsImpl.closeSync(fd);}}
module.exports={readStableRegularFile};
