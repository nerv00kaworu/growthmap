'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {reserveDistinctPort}=require('../sidecar-port-reservation');

test('sidecar retries reject reused ephemeral port values within one sequence',async()=>{
 const used=new Set(),values=[43123,43123,43124,43124,43125],reserve=async()=>values.shift();
 assert.equal(await reserveDistinctPort(used,reserve),43123);
 assert.equal(await reserveDistinctPort(used,reserve),43124);
 assert.equal(await reserveDistinctPort(used,reserve),43125);
 assert.deepEqual([...used],[43123,43124,43125]);
});

test('distinct port reservation fails bounded when Windows keeps recycling one value',async()=>{
 const used=new Set([43123]);let calls=0;
 await assert.rejects(()=>reserveDistinctPort(used,async()=>{calls++;return 43123}),/Could not reserve a distinct sidecar retry port/);
 assert.equal(calls,32);
});

test('distinct port reservation validates authority inputs',async()=>{
 await assert.rejects(()=>reserveDistinctPort([],async()=>1),TypeError);
 await assert.rejects(()=>reserveDistinctPort(new Set(),null),TypeError);
});
