'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const test=require('node:test');
const {appPageIdentity,equivalent,scan}=require('../scripts/csp-manifest');

const PAGE='(e,t,r)=>{"use strict";r.r(t),r.d(t,{default:()=>function Page(){return"safe"}})}';
function boot(reference){return `(e,t,r)=>{Promise.resolve().then(r.bind(r,"${reference}"))}`;}
function chunk(id='bootstrap',page=PAGE,chunkList='["app/page"]',extra='',pageId='page',reference=pageId){
  return `(self.webpackChunk_N_E=self.webpackChunk_N_E||[]).push([${chunkList},{"${id}":${boot(reference)},"${pageId}":${page}${extra}},123]);`;
}
function output(source,name='page-linux.js'){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'csp-semantic-'));const app=path.join(root,'_next','static','chunks','app');fs.mkdirSync(app,{recursive:true});
  fs.writeFileSync(path.join(app,name),source);fs.writeFileSync(path.join(root,'index.html'),`<script>self.__next_f.push([1,"${name}"])</script>`);return root;
}

test('renamed referenced page module ID preserves semantic identity',()=>{
  const linux=scan(output(chunk('35a84c1952d2be21',PAGE,'["app/page"]','','linuxPageModule'),'page-a82e37eee192a225.js'));
  const windows=scan(output(chunk('13a57e87b06252d4',PAGE,'["app/page"]','','c546470e5ca77f8d'),'page-9642f8737efe1b56.js'));
  assert.equal(equivalent(linux,windows),true);
  assert.notEqual(linux.evidence.appPage.sha256,windows.evidence.appPage.sha256);
  assert.notEqual(linux.hashes[0],windows.hashes[0]);
});

test('changed local module reference topology fails semantic verification',()=>{
  const expected=scan(output(chunk('bootstrap',PAGE,'["app/page"]','','page','page')));
  const changed=scan(output(chunk('bootstrap',PAGE,'["app/page"]','','page','bootstrap')));
  assert.equal(equivalent(expected,changed),false);
});

test('changed page factory source fails semantic verification',()=>{
  const left=scan(output(chunk()));const right=scan(output(chunk('bootstrap',PAGE.replace('"safe"','"changed"'))));
  assert.equal(equivalent(left,right),false);
});

test('changed chunk tuple zero fails semantic verification',()=>{
  assert.equal(equivalent(scan(output(chunk())),scan(output(chunk('bootstrap',PAGE,'["app/other"]')))),false);
});

test('source count change fails semantic verification',()=>{
  assert.equal(equivalent(scan(output(chunk())),scan(output(chunk('bootstrap',PAGE,'["app/page"]',`,extra:(e,t,r)=>{"use strict"}`)))),false);
});

test('factory identity is independent of module-map order but includes every exact source digest',()=>{
  const left=appPageIdentity(chunk());
  const reordered=`(self.webpackChunk_N_E=self.webpackChunk_N_E||[]).push([["app/page"],{page:${PAGE},bootstrap:${boot('page')}},123]);`;
  assert.deepEqual(left,appPageIdentity(reordered));
  assert.equal(left.sourceCount,2);assert.equal(left.sources.length,2);assert.match(left.sources[0].sha256,/^[0-9a-f]{64}$/);
});

test('malformed emitted chunks fail closed',()=>{
  for(const source of ['', 'not webpack', '(x=[]).push([["app/page"],{},123]);', '(x=[]).push([["app/page"],{id:42},123]);', '(x=[]).push([["app/page"],{id:(e)=>{}},123,4]);'])
    assert.throws(()=>appPageIdentity(source),/app page|unsupported|factory/);
});
