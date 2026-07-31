'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createSessionAuthority}=require('../session-authority');
const {createRequestPolicy}=require('../request-policy');

test('trusted main process rotates the desktop bearer for each sidecar bootstrap',()=>{
 const values=[Buffer.alloc(32,1),Buffer.alloc(32,2)],authority=createSessionAuthority(()=>values.shift());
 assert.throws(()=>authority.current(),/not initialized/);
 const oldSession=authority.rotate(),policy=createRequestPolicy({getBaseUrl:()=> 'http://127.0.0.1:41001',getToken:()=>authority.current(),csp:"default-src 'self'"});
 assert.equal(policy.before({url:'http://127.0.0.1:41001/api/projects'}).requestHeaders.Authorization,`Bearer ${oldSession}`);
 const newSession=authority.rotate();
 assert.notEqual(newSession,oldSession);
 assert.equal(policy.before({url:'http://127.0.0.1:41001/api/projects'}).requestHeaders.Authorization,`Bearer ${newSession}`);
});

test('no sidecar rebootstrap retains no alternate desktop session path',()=>{
 const authority=createSessionAuthority(()=>Buffer.alloc(32,3)),session=authority.rotate();
 assert.equal(authority.current(),session);
 assert.equal(Object.keys(authority).sort().join(','),'current,rotate');
});
