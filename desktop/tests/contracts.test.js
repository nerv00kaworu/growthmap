const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');const main=fs.readFileSync(require.resolve('../main.js'),'utf8'),preload=fs.readFileSync(require.resolve('../preload.js'),'utf8'),pkg=require('../package.json');test('shell hardening',()=>{for(const x of ['requestSingleInstanceLock','nodeIntegration:false','contextIsolation:true','sandbox:true','setWindowOpenHandler','will-navigate','127.0.0.1'])assert.match(main,new RegExp(x));});test('token header only',()=>{assert.match(main,/randomBytes\(32\)/);assert.match(main,/Authorization/);assert.doesNotMatch(main,/localStorage|searchParams/);});test('desktop update and database recovery IPC contracts are exposed',()=>{for(const value of ["'updates:check'","'database:backup'","'database:list-backups'","'database:reveal'","'database:import'","'database:restore'"])assert.match(preload,new RegExp(value));assert.match(main,/updateRecovery/);assert.match(main,/method==='restore'&&!updateRecovery/);const page=fs.readFileSync(require('node:path').resolve(__dirname,'../../src/frontend/src/app/page.tsx'),'utf8');assert.match(page,/data-testid="check-updates-button"/);assert.match(page,/growthmapDesktop\.updates\.check\(\)/);});
test('safeStorage write-only IPC',()=>{assert.match(main,/safeStorage\.encryptString/);assert.match(main,/isEncryptionAvailable/);assert.deepEqual([...preload.matchAll(/'secrets:(has|set|delete)'/g)].map(x=>x[1]).sort(),['delete','has','set']);});test('NSIS',()=>{assert.equal(pkg.build.nsis.oneClick,true);assert.equal(pkg.build.win.target[0].target,'nsis');});
test('IPC guard and strict CSP/lifecycle contracts',()=>{assert.match(main,/event\.sender!==expected/);assert.match(main,/senderFrame/);assert.match(main,/origin!==baseUrl/);assert.match(main,/policy\(manifest\)/);assert.doesNotMatch(main,/unsafe-eval/);assert.match(main,/onHeadersReceived/);assert.match(main,/for\(let attempt=1;attempt<=3/);assert.match(main,/exited before readiness/);assert.match(main,/stopped unexpectedly/);});

test('dynamic loopback hook is broad but request policy checks current origin',()=>{assert.match(main,/createRequestPolicy/);assert.match(require('node:fs').readFileSync(require.resolve('../request-policy.js'),'utf8'),/127\.0\.0\.1:\*\/\*/);});

test('native menu removed and renderer diagnostics/error fallback wired',()=>{for(const x of ['Menu.setApplicationMenu(null)','autoHideMenuBar:true','setMenu(null)','did-fail-load','render-process-gone','console-message'])assert.match(main,new RegExp(x.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));assert.match(main,/title:'GrowthMap'/);});

test('entitlement changes invalidate renderer state without weakening the IPC origin guard',()=>{
 const page=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/app/page.tsx'),'utf8');
 const hook=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/lib/entitlement.ts'),'utf8');
 const api=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/lib/api.ts'),'utf8');
 assert.match(preload,/desktop:entitlement-changed/);assert.match(preload,/removeListener\('desktop:entitlement-changed'/);
 assert.match(main,/const imported=.*license\/import/);assert.match(main,/notifyEntitlementChanged\(\);return imported/);
 assert.match(main,/notifyEntitlementChanged\(\);child\.once\('exit'/);
 assert.match(main,/event\.sender!==expected/);assert.match(main,/origin!==baseUrl/);
 assert.match(hook,/entitlement\.onChanged/);assert.match(hook,/refreshEntitlement/);assert.match(hook,/requestSequence/);
 assert.match(api,/getEntitlement:.*cache: "no-store"/);
 assert.match(page,/entitlement === null \? "Checking entitlement…"/);assert.match(page,/mutations_allowed !== true/);
});

test('license import and extraction-to-trial transitions revalidate authoritative entitlement',()=>{
 const page=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/app/page.tsx'),'utf8');
 const hook=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/lib/entitlement.ts'),'utf8');
 assert.match(page,/await desktop\.license\.import\(\)/);assert.match(page,/await refreshEntitlement\(\)/);
 assert.match(hook,/onChanged\(\(\) =>/);assert.match(hook,/api\.getEntitlement\(\)/);
 assert.doesNotMatch(hook,/setInterval|setTimeout/);
});
test('production package verifier uses a CRLF fixture and checks actual ASAR/resource boundaries',()=>{
 const script=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/scripts/verify-production-asar.ps1'),'utf8');
 const fixture=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/scripts/fixtures/production-package-layout.json'),'utf8'));
 for(const entry of ['updater.js','update-recovery.js','update-policy.js','managed-backup.js','startup-verdict.js','commercial-config.js','product-identity.json'])assert.ok(fixture.requiredAsarEntries.includes(entry),`missing ASAR contract ${entry}`);
 assert.ok(fixture.requiredResourceEntries.includes('commercial-config.json'));
 assert.ok(fixture.asarListLines.some(entry=>entry.startsWith('\\')&&entry.endsWith('\r')));
 assert.ok(fixture.asarListLines.some(entry=>entry.startsWith('/')&&entry.endsWith('\r')));
 assert.match(script,/\.Trim\(\)/);assert.match(script,/-replace '\\\\', '\/'/);assert.match(script,/-replace '\^\/\+'/);
 assert.match(script,/npx --yes '@electron\/asar' list \$asar/);
 assert.match(script,/GetRelativePath\(\$resources/);
 assert.match(script,/Assert-NoProductionTestEntries \$ResourceEntries 'resources'/);
 assert.match(script,/commercial-config\.json is intentionally an extraResource/);
 assert.match(script,/Get-FileHash \$commercialPath/);
 for(const field of ['paymentApiOrigin','purchasePortalOrigin','purchasePortalUrl','baseNetwork','baseUsdc','basePayee','earlyLimit','earlyPriceMicros','regularPriceMicros','paypalUrl'])assert.match(script,new RegExp(`'${field}'`));
 for(const serverOnly of ['growthmap_payments','services/payments','admin_secret','signing_key'])assert.match(script,new RegExp(`'${serverOnly.replace('/','\\/')}'`));
 for(const forbiddenExtension of ['py','pem','sqlite3'])assert.match(script,new RegExp(forbiddenExtension));
 assert.match(script,/migrations\?/);
 for(const contentMarker of ['BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY','SQLite format 3','Ed25519PrivateKey','CREATE TABLE settlement_intents'])assert.ok(script.includes(contentMarker));
 assert.match(script,/Assert-NoForbiddenContent \(Join-Path \$tmp 'all'\) 'ASAR'/);
 assert.match(script,/Assert-NoForbiddenContent \$resources 'resources'/);
 assert.match(script,/@\{ Name='blob\.dat'/);assert.match(script,/@\{ Name='cache\.bin'/);assert.match(script,/@\{ Name='worker\.dat'/);
 assert.doesNotMatch(script,/extract-file \$asar commercial-config\.json/);
});
test('Windows database boundary fixtures are isolated under canonical system temp',()=>{
 const script=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/scripts/test-windows-database-boundaries.ps1'),'utf8');
 assert.match(script,/\[System\.IO\.Path\]::GetTempPath\(\)/);
 assert.match(script,/Assert-SystemTempChild \$root/);
 assert.match(script,/Test-CanonicalChildPath -Path \$root -Parent \$repositoryRoot/);
 assert.match(script,/create-e2e-fixture\.py' \$repoFixture/);
 assert.match(script,/Fixture helper unexpectedly accepted a repository output path/);
 assert.doesNotMatch(script,/Join-Path \$env:RUNNER_TEMP/);
});
test('pending-update lock precedes recovery, schema, migration backup and writable policy',()=>{const source=fs.readFileSync(require('node:path').join(__dirname,'../main.js'),'utf8'),body=source.slice(source.indexOf('async function prepareAndStart'),source.indexOf('async function launch'));const pending=body.indexOf('if(pending)'),verify=body.indexOf('verifyPending'),recover=body.indexOf('recoverStartup'),schema=body.indexOf('schemaStatus'),backup=body.indexOf('migrationBackup');assert(pending>=0&&verify>pending&&recover>verify&&schema>recover&&backup>schema);assert.match(body,/await lifecycle\.cleanup\(\)/);});
test('packaged launch scrubs attacker trust env and injects bundled key mode',()=>{const source=fs.readFileSync(require('node:path').join(__dirname,'../main.js'),'utf8');for(const key of ['GROWTHMAP_CHECKOUT_ORIGIN','GROWTHMAP_CHECKOUT_URL','GROWTHMAP_UPDATE_URL','GROWTHMAP_LICENSE_PUBLIC_KEY'])assert.match(source,new RegExp(key));assert.match(source,/GROWTHMAP_BUNDLED_LICENSE_PUBLIC_KEY/);assert.match(source,/GROWTHMAP_PACKAGED_MODE/);});

test('Windows dependency provenance is passed by immutable step outputs, never GITHUB_ENV', () => {
  const workflow = fs.readFileSync(path.resolve(__dirname, '../../.github/workflows/desktop-windows.yml'), 'utf8')
  const verifier = fs.readFileSync(path.resolve(__dirname, '../../.github/workflows/scripts/verify-production-asar.ps1'), 'utf8')
  const provenance = fs.readFileSync(path.resolve(__dirname, '../../.github/workflows/scripts/new-node-provenance.ps1'), 'utf8')
  assert.match(workflow, /path=\$path.*GITHUB_OUTPUT/s)
  assert.match(workflow, /sha256=\$digest.*GITHUB_OUTPUT/s)
  assert.match(workflow, /^\s*run: \.\/\.github\/workflows\/scripts\/verify-production-asar\.ps1 -ProvenancePath \$\{\{ steps\.dependency-provenance\.outputs\.path \}\} -ProvenanceSha256 \$\{\{ steps\.dependency-provenance\.outputs\.sha256 \}\}\s*$/m)
  assert.doesNotMatch(workflow, /\$env:GITHUB_ENV/)
  assert.match(verifier, /param\(\[switch\]\$SelfTestOnly,\[string\]\$ProvenancePath,\[string\]\$ProvenanceSha256\)/)
  assert.doesNotMatch(verifier, /\$env:GITHUB_ENV/)
  assert.doesNotMatch(provenance, /\$env:GITHUB_ENV/)
})
