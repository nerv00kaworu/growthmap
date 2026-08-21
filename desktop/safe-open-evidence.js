'use strict';
const fs=require('node:fs'),crypto=require('node:crypto');
function digestFd(fd,size){const bytes=Buffer.alloc(size);let read=0;while(read<size){const n=fs.readSync(fd,bytes,read,size-read,read);if(!n)break;read+=n}const data=bytes.subarray(0,read);return {sha256:crypto.createHash('sha256').update(data).digest('hex'),size:data.length}}
async function openEvidence(file,_validate,{nativeOpen=null,platform=process.platform}={}){
 if(nativeOpen)return nativeOpen(file,_validate);if(platform==='win32'){const e=Error('Windows replacement recovery requires native opened-handle evidence');e.code='REPLACEMENT_EVIDENCE_UNAVAILABLE';throw e}
 const nofollow=fs.constants.O_NOFOLLOW||0,fd=fs.openSync(file,fs.constants.O_RDONLY|nofollow);let closed=false;const close=async()=>{if(closed)return;closed=true;fs.closeSync(fd)};
 try{const before=fs.fstatSync(fd);if(!before.isFile()||before.nlink!==1)throw Error('Replacement evidence handle is unsafe');const evidence=digestFd(fd,before.size),named=fs.lstatSync(file);if(!named.isFile()||named.isSymbolicLink()||named.nlink!==1||named.dev!==before.dev||named.ino!==before.ino)throw Error('Replacement evidence path changed');return {evidence,identity:{dev:String(before.dev),ino:String(before.ino)},fd,file,async assertExact(expected){await this.assertPath();const current=digestFd(fd,fs.fstatSync(fd).size);if(current.sha256!==expected.sha256||current.size!==expected.size)throw Error('Replacement evidence bytes changed')},async assertPath(){const now=fs.lstatSync(file),held=fs.fstatSync(fd);if(!now.isFile()||now.isSymbolicLink()||now.nlink!==1||now.dev!==held.dev||now.ino!==held.ino)throw Error('Replacement evidence path changed')},close};}catch(error){await close();throw error}
}
module.exports={openEvidence};
