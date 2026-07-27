const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {scan,stable,verify}=require('../scripts/csp-manifest'),{loadManifest,policy}=require('../csp');
const out=path.resolve(__dirname,'../../src/frontend/out'),file=path.resolve(__dirname,'../generated/csp-script-hashes.json');
test('manifest deterministically covers every inline script in every exported HTML file',()=>{const manifest=loadManifest(file);assert.deepEqual(verify(manifest,out),scan(out));assert.equal(fs.readFileSync(file,'utf8'),stable(scan(out)));assert(Object.keys(manifest.files).length>0);assert(manifest.hashes.length>0);});
test('script CSP uses only self and SHA-256 hashes',()=>{const value=policy(loadManifest(file));assert.match(value,/script-src 'self' 'sha256-/);assert.doesNotMatch(value,/script-src[^;]*'unsafe-inline'/);assert.doesNotMatch(value,/unsafe-eval/);assert.match(value,/connect-src 'self'/);});
