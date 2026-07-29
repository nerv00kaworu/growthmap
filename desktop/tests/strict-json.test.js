'use strict';
const test=require('node:test'),assert=require('node:assert/strict');const {parseStrictJson}=require('../strict-json');
test('raw duplicate and case-colliding keys are rejected before last-key collapse',()=>{for(const raw of ['{"product":"evil","product":"growthmap"}','{"license_id":"x","LICENSE_ID":"y"}','{"outer":{"sequence":0,"sequence":1}}'])assert.throws(()=>parseStrictJson(raw),/Duplicate|colliding/);assert.deepEqual(parseStrictJson('{"product":"growthmap","sequence":1}'),{product:'growthmap',sequence:1});});
