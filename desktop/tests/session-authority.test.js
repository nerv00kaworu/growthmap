'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createSessionAuthority}=require('../session-authority');
const {createRequestPolicy}=require('../request-policy');

test('trusted main commits a candidate only after bootstrap and rotates bearer',()=>{
 const values=[Buffer.alloc(32,1),Buffer.alloc(32,2)],authority=createSessionAuthority(()=>values.shift());
 assert.throws(()=>authority.current(),/not initialized/);
 const first=authority.begin();assert.equal(authority.candidate(first),first.token);assert.throws(()=>authority.current(),/not initialized/);
 authority.commit(first);const policy=createRequestPolicy({getBaseUrl:()=> 'http://127.0.0.1:41001',getToken:()=>authority.current(),csp:"default-src 'self'"});
 assert.equal(policy.before({url:'http://127.0.0.1:41001/api/projects'}).requestHeaders.Authorization,`Bearer ${first.token}`);
 const second=authority.begin();assert.notEqual(second.token,first.token);assert.equal(authority.current(),first.token,'unverified candidate is not current');
 authority.commit(second);assert.equal(authority.current(),second.token);assert.throws(()=>authority.commit(first),/stale/);
});

test('probe/start failure invalidates all renderer and main HTTP authority',()=>{
 const authority=createSessionAuthority(()=>Buffer.alloc(32,3)),candidate=authority.begin();authority.commit(candidate);
 authority.invalidate();assert.throws(()=>authority.current(),/not initialized/);
 const next=authority.begin();authority.invalidate(next);assert.throws(()=>authority.current(),/not initialized/);assert.throws(()=>authority.candidate(next),/stale/);
});

test('authority surface has no renderer/preload alternate session path',()=>{
 const authority=createSessionAuthority(()=>Buffer.alloc(32,4));
 assert.equal(Object.keys(authority).sort().join(','),'begin,candidate,commit,current,invalidate');
});
