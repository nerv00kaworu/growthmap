'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex'),residue=/\.(?:gm-old|gm-failed|gm-new)-|\.quarantine|\.failed-|\.capture$/;
function exact(file,bytes){assert.equal(fs.existsSync(file),true,`missing ${file}`);const stat=fs.lstatSync(file);assert.equal(stat.isFile(),true);assert.equal(stat.isSymbolicLink(),false);assert.equal(stat.nlink,1);const actual=fs.readFileSync(file);assert.equal(actual.length,bytes.length);assert.equal(hash(actual),hash(bytes));assert.deepEqual(actual,bytes)}
function listing(db){return fs.readdirSync(path.dirname(db)).filter(x=>residue.test(x)).sort()}
function authorityExact(file,value){assert.deepEqual(JSON.parse(fs.readFileSync(file,'utf8')),value)}
function rollbackOracle({db,intent,authorityFile,authorityPre}){exact(db,Buffer.from('OLD'));exact(intent.failedPath,Buffer.from('NEW'));assert.equal(fs.existsSync(intent.oldPath),false);assert.equal(fs.existsSync(intent.quarantinePath),false);authorityExact(authorityFile,authorityPre);assert.deepEqual(listing(db),[path.basename(intent.failedPath)])}
function committedOracle({db,intent,authorityFile,authorityNew}){exact(db,Buffer.from('NEW'));exact(intent.quarantinePath,Buffer.from('OLD'));assert.equal(fs.existsSync(intent.failedPath),false);assert.equal(fs.existsSync(intent.oldPath),false);authorityExact(authorityFile,authorityNew);assert.deepEqual(listing(db),[path.basename(intent.quarantinePath)])}
module.exports={exact,listing,rollbackOracle,committedOracle};
