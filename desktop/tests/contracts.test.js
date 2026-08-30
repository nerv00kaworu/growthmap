const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');const main=fs.readFileSync(require.resolve('../main.js'),'utf8'),preload=fs.readFileSync(require.resolve('../preload.js'),'utf8'),pkg=require('../package.json');test('shell hardening',()=>{for(const x of ['requestSingleInstanceLock','nodeIntegration:false','contextIsolation:true','sandbox:true','setWindowOpenHandler','will-navigate','127.0.0.1'])assert.match(main,new RegExp(x));});test('token header only',()=>{assert.match(main,/randomBytes\(32\)/);assert.match(main,/Authorization/);assert.doesNotMatch(main,/localStorage|searchParams/);});
test('running sidecar gets the current token only after inherited launch environment scrubbing',()=>{assert.match(main,/sidecarSessionEnv\(scrubLaunchEnv\(\{\.\.\.process\.env\}\),token\)/);assert.match(main,/GROWTHMAP_SESSION_TOKEN/);});test('desktop update and database recovery IPC contracts are exposed',()=>{for(const value of ["'updates:check'","'database:backup'","'database:list-backups'","'database:reveal'","'database:import'","'database:restore'"])assert.match(preload,new RegExp(value));assert.match(main,/updateRecovery/);assert.match(main,/method==='restore'&&!updateRecovery/);const page=fs.readFileSync(require('node:path').resolve(__dirname,'../../src/frontend/src/app/page.tsx'),'utf8');assert.match(page,/data-testid="check-updates-button"/);assert.match(page,/growthmapDesktop\.updates\.check\(\)/);});
test('every direct local main dependency ships in the production ASAR allowlist',()=>{const shipped=new Set(pkg.build.files.filter(value=>typeof value==='string'&&!value.startsWith('!')));for(const match of main.matchAll(/require\(['"](\.\/[A-Za-z0-9_-]+)['"]\)/g)){const entry=`${match[1].slice(2)}.js`;assert.ok(shipped.has(entry),`main.js local dependency missing from package files: ${entry}`);}});
test('dynamic async durability modules are exact ASAR sources and package-verifier contracts',()=>{const required=['credential-lineage-async.js','replacement-journal-async.js'],files=pkg.build.files;for(const entry of required){assert.equal(files.filter(x=>x===entry).length,1);assert(fs.existsSync(path.resolve(__dirname,'..',entry)));}assert.doesNotMatch(files.join('\n'),/(?:credential-lineage|replacement-journal)[*?]/);const fixture=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/scripts/fixtures/production-package-layout.json'),'utf8'));for(const entry of required){assert(fixture.requiredAsarEntries.includes(entry));assert(fixture.asarListLines.map(x=>x.trim().replace(/^[/\\]/,'')).includes(entry));}});
test('desktop contains no payee clipboard, rail, wallet, or payment-signature IPC',()=>{const page=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/app/page.tsx'),'utf8');for(const source of [main,preload,page])assert.doesNotMatch(source,/copy-base-payee|copyBasePayee|basePayee|PAYMENT-SIGNATURE|walletSignature|paypal|USDC on Base/);assert.doesNotMatch(page,/navigator\.clipboard/);});
test('purchase IPC opens one exact website with no rail or renderer context',()=>{assert.match(main,/purchase:open'.*\.\.\.args.*purchaseTargetForArgs\(args,commercialConfig\)/s);assert.match(preload,/open:\(\)=>ipcRenderer\.invoke\('purchase:open'\)/);assert.doesNotMatch(preload,/open:\(rail|orderContext|recoveryContext/);});
test('activation IPC accepts one key and imports only returned certificate',()=>{assert.match(main,/license:activate'.*guard\(e\).*activateLicenseKey.*license\/import.*notifyEntitlementChanged/s);assert.match(preload,/activate:key=>ipcRenderer\.invoke\('license:activate',key\)/);const page=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/app/page.tsx'),'utf8');assert.match(page,/activation-key-input/);assert.match(page,/growthmapDesktop\.license\.activate\(activationKey\)/);});
test('safeStorage write-only IPC',()=>{assert.match(main,/safeStorage\.encryptString/);assert.match(main,/isEncryptionAvailable/);assert.deepEqual([...preload.matchAll(/'secrets:(has|set|delete)'/g)].map(x=>x[1]).sort(),['delete','has','set']);});test('NSIS',()=>{assert.equal(pkg.build.nsis.oneClick,true);assert.equal(pkg.build.win.target[0].target,'nsis');});
test('IPC guard and strict CSP/lifecycle contracts',()=>{const readiness=fs.readFileSync(require.resolve('../sidecar-readiness.js'),'utf8');assert.match(main,/event\.sender!==expected/);assert.match(main,/senderFrame/);assert.match(main,/origin!==baseUrl/);assert.match(main,/policy\(manifest\)/);assert.doesNotMatch(main,/unsafe-eval/);assert.match(main,/onHeadersReceived/);assert.match(main,/for\(let attempt=1;attempt<=3/);assert.match(readiness,/exited before readiness/);assert.match(main,/stopped unexpectedly/);});

test('Agent Grant caller-ID commit races map to closed safe HTTP outcomes',()=>{const route=fs.readFileSync(path.resolve(__dirname,'../../src/backend/agent_port/routes.py'),'utf8');assert.match(route,/from sqlalchemy\.exc import IntegrityError/);const handler=route.slice(route.indexOf('async def create_grant'),route.indexOf('@human_router.post("/agent-port/grants/{old_grant_id}/rotate"'));assert.match(handler,/except IntegrityError:\s*\n\s*await db\.rollback\(\)/);assert.match(handler,/if await db\.get\(AgentGrant,grant_id\): raise HTTPException\(409,\{"code":"ID_CONFLICT"/);assert.match(handler,/raise HTTPException\(503,"Unable to allocate grant"\)/);assert.doesNotMatch(route,/except IntegrityError:[\s\S]{0,500}(?:str\(.*error|repr\()/);});

test('Agent Access HTTP uses per-call streaming success ceilings',()=>{assert.match(main,/function api\(method,route,body,extraHeaders=\{\},responseOptions=\{\}\)/);assert.match(main,/readResponse\(r,responseOptions\)/);const access=fs.readFileSync(require.resolve('../agent-access.js'),'utf8');assert.match(access,/grants\?project_id=[\s\S]{0,180}maxSuccessBytes:MAX_STATUS_BYTES/);assert.match(access,/api\('POST','\/api\/agent-port\/grants',[\s\S]{0,180}maxSuccessBytes:16384/);});

test('all Agent Access IPC registrations use the safe main-process boundary',()=>{assert.match(main,/registerAgentAccessIpc\(\{ipcMain,guard,getAgentAccess:\(\)=>agentAccess/);assert.doesNotMatch(main,/ipcMain\.handle\('agent-access:/);const boundary=fs.readFileSync(require.resolve('../agent-access-ipc.js'),'utf8');for(const name of ['status','enable','disable','copy','download','test','regenerate'])assert.ok(boundary.includes(name));assert.match(boundary,/GROWTHMAP_DESKTOP_ERROR/);assert.doesNotMatch(boundary,/error\.message|error\.stack/);});

test('unused Agent Access config IPC is absent and sensitive surfaces remain manager-authorized',()=>{assert.doesNotMatch(main,/agent-access:config/);assert.doesNotMatch(preload,/agent-access:config/);for(const method of ['copyConfig','downloadConfig','test','regenerateImpl'])assert.match(fs.readFileSync(require.resolve('../agent-access.js'),'utf8'),new RegExp(`${method}[\\s\\S]{0,220}authorize\\(`));});

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
 assert.match(page,/entitlement === null \? t\("entitlement\.checking"\)/);assert.match(page,/mutations_allowed !== true/);
});

test('entitlement preflight binds fresh existing-Free paid and extraction startup modes',()=>{assert.match(main,/entitlementStatus\(userData,trialMode\)/);assert.match(main,/trialMode==='existing'\?'free':trialMode==='fresh'\?'fresh':'extraction'/);assert.match(main,/GROWTHMAP_FRESH_INSTALL:probeMode==='fresh'\?'1':'0'/);assert.match(main,/entitlementStatus\(userData,trial\.mode\)/);});
test('direct packaged sidecar smoke supplies a real v2 fresh verdict rather than bypassing startup authentication',()=>{const script=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/scripts/verify-windows-package.ps1'),'utf8');for(const marker of ["require('./desktop/startup-verdict')","generateKeyPairSync('ed25519')","createStartupVerdict({mode:'fresh'","startupVerdictEnv({verdict,token})","GROWTHMAP_FRESH_INSTALL = '1'","SetEnvironmentVariable($entry.Name"])assert.ok(script.includes(marker),`packaged sidecar smoke missing ${marker}`);assert.doesNotMatch(script,/GROWTHMAP_STARTUP_VERDICT_MAC\s*=\s*['\"]/);});

test('license import and extraction-to-Free transitions revalidate authoritative entitlement',()=>{
 const page=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/app/page.tsx'),'utf8');
 const hook=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/lib/entitlement.ts'),'utf8');
 assert.match(page,/await desktop\.license\.import\(\)/);assert.match(page,/await refreshEntitlement\(\)/);
 assert.match(hook,/onChanged\(\(\) =>/);assert.match(hook,/api\.getEntitlement\(\)/);
 assert.doesNotMatch(hook,/setInterval|setTimeout/);
});
test('production package verifier uses a CRLF fixture and checks actual ASAR/resource boundaries',()=>{
 const script=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/scripts/verify-production-asar.ps1'),'utf8');
 const fixture=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/scripts/fixtures/production-package-layout.json'),'utf8'));
 for(const entry of ['updater.js','update-recovery.js','update-policy.js','managed-backup.js','startup-verdict.js','commercial-config.js','purchase-portal.js','product-identity.json','revocation-store.js','license-freshness-store.js','protected-history.js','strict-json.js'])assert.ok(fixture.requiredAsarEntries.includes(entry),`missing ASAR contract ${entry}`);
 assert.ok(fixture.requiredResourceEntries.includes('commercial-config.json'));
 assert.ok(fixture.asarListLines.some(entry=>entry.startsWith('\\')&&entry.endsWith('\r')));
 assert.ok(fixture.asarListLines.some(entry=>entry.startsWith('/')&&entry.endsWith('\r')));
 assert.match(script,/\.Trim\(\)/);assert.match(script,/-replace '\\\\', '\/'/);assert.match(script,/-replace '\^\/\+'/);
 assert.match(script,/& node \$asarCli list \$asar/);
 assert.match(script,/GetRelativePath\(\$resources/);
 assert.match(script,/Assert-NoProductionTestEntries \$ResourceEntries 'resources'/);
 assert.match(script,/commercial-config\.json is intentionally an extraResource/);
 assert.match(script,/Get-FileHash \$commercialPath/);
 for(const field of ['licenseIssuer','supportEmail','supportUrl','activationApiOrigin','purchasePortalOrigin','purchasePortalUrl'])assert.match(script,new RegExp(`'${field}'`));
 for(const removed of ['paymentApiOrigin','baseNetwork','baseUsdc','basePayee','earlyPriceMicros','regularPriceMicros','paypalUrl'])assert.doesNotMatch(script,new RegExp(`'${removed}'`));
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

test('commercial Windows preflight requires signing credentials while unsigned CI remains explicitly noncommercial',()=>{const preflight=fs.readFileSync(path.resolve(__dirname,'../scripts/preflight.js'),'utf8'),workflow=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/desktop-windows.yml'),'utf8');assert.match(preflight,/WIN_CSC_LINK&&process\.env\.WIN_CSC_KEY_PASSWORD/);assert.match(preflight,/!signed/);assert.match(workflow,/noncommercial unsigned NSIS test installer/);assert.match(workflow,/Unknown Publisher/);});
test('final packaged-main smoke uses an isolated real user-profile parent, not runner temp',()=>{const workflow=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/desktop-windows.yml'),'utf8'),step=workflow.slice(workflow.indexOf('- name: Launch final unsigned package with real production main'),workflow.indexOf('- name: Verify final production resources'));assert.match(step,/Join-Path \$env:LOCALAPPDATA "growthmap-final-main-smoke-\$env:GITHUB_RUN_ID-\$env:GITHUB_RUN_ATTEMPT"/);assert.match(step,/if \(Test-Path \$profile\) \{ throw/);assert.doesNotMatch(step,/\$profile\s*=\s*Join-Path \$env:RUNNER_TEMP/);});
test('Windows dependency provenance is passed by immutable step outputs, never GITHUB_ENV', () => {
  const workflow = fs.readFileSync(path.resolve(__dirname, '../../.github/workflows/desktop-windows.yml'), 'utf8')
  const verifier = fs.readFileSync(path.resolve(__dirname, '../../.github/workflows/scripts/verify-production-asar.ps1'), 'utf8')
  const provenance = fs.readFileSync(path.resolve(__dirname, '../../.github/workflows/scripts/new-node-provenance.ps1'), 'utf8')
  assert.match(workflow, /path=\$path.*GITHUB_OUTPUT/s)
  assert.match(workflow, /sha256=\$digest.*GITHUB_OUTPUT/s)
  assert.match(workflow, /^\s*run: \.\/\.github\/workflows\/scripts\/verify-production-asar\.ps1 -ProvenancePath \$\{\{ steps\.dependency-provenance\.outputs\.path \}\} -ProvenanceSha256 \$\{\{ steps\.dependency-provenance\.outputs\.sha256 \}\}\s*$/m)
  const provenanceStep = workflow.slice(workflow.indexOf('- name: Freeze clean desktop dependency provenance'), workflow.indexOf('- run: npm test'))
  assert.doesNotMatch(provenanceStep, /\$env:GITHUB_ENV/)
  assert.match(verifier, /param\(\[switch\]\$SelfTestOnly,\[string\]\$ProvenancePath,\[string\]\$ProvenanceSha256\)/)
  assert.match(verifier, /ConvertFrom-Json -Depth 100 -AsHashtable/)
  assert.match(verifier, /\$lock\['packages'\]\[''\]/)
  assert.match(verifier, /\$rootDependencyNames = \(\(\$rootDeps\.Keys \| Sort-Object\) -join "`n"\)/)
  assert.match(verifier, /\$lockRootDependencyNames = \(\(\$lockRootDeps\.Keys \| Sort-Object\) -join "`n"\)/)
  assert.ok((verifier.match(/\$testDigest=& \(Join-Path \$PSScriptRoot 'new-node-provenance\.ps1'\)/g)||[]).length >= 4)
  assert.match(verifier, /Refresh the[\s\S]*synthetic frozen provenance after each deliberate fixture mutation/)
  assert.match(verifier, /\$_.Name -cne '\.bin'/)
  assert.match(verifier, /foreach\(\$file in Get-ChildItem \$source -File -Force -Recurse\)/)
  assert.match(verifier, /\$meta\['dev'\] -eq \$true/)
  assert.match(verifier, /\$sourceByIdentity/)
  assert.match(verifier, /\$prunableManifestFields=@\('bugs','contributors','eslintConfig','keywords','scripts','xo'\)/)
  assert.match(verifier, /adds, modifies, or removes runtime-semantic frozen metadata/)
  assert.match(verifier, /Dictionary\[string,object\].*StringComparer\]::Ordinal/)
  assert.match(verifier, /foreach \(\$requiredField in @\('main','exports','type','bin'\)\)/)
  assert.match(verifier, /foreach \(\$caseVariant in @\(@\{Exact='main';Variant='MAIN'\},@\{Exact='exports';Variant='EXPORTS'\},@\{Exact='type';Variant='TYPE'\},@\{Exact='bin';Variant='BIN'\}\)\)/)
  assert.match(verifier, /Inventory accepted removal of runtime package field/)
  assert.match(verifier, /Inventory accepted case-renamed runtime package field/)
  assert.ok((verifier.match(/absent or byte-different from same-identity frozen inventory/g)||[]).length >= 2)
  assert.doesNotMatch(verifier, /differs from lock-installed inventory/)
  assert.match(verifier, /\$safeManifest='\{\"name\":\"safe-package\",\"version\":\"1\.0\.0\",\"main\":\"index\.js\",\"type\":\"commonjs\",\"exports\":\"\.\/index\.js\"/)
  assert.match(verifier, /safe-package\/package\.json/)
  assert.match(verifier, /\$installed = Join-Path \$contentRoot 'node_modules'/)
  assert.doesNotMatch(verifier, /\$installed = Join-Path \$contentRoot 'installed'/)
  assert.doesNotMatch(verifier, /\$lock\.packages/)
  assert.doesNotMatch(verifier, /\$env:GITHUB_ENV/)
  assert.doesNotMatch(provenance, /\$env:GITHUB_ENV/)
})
test('expired paid identity reaches freshness high-water while Free and no-license do not',()=>{const main=fs.readFileSync(path.resolve(__dirname,'../main.js'),'utf8');assert.match(main,/else if\(entitlement\.license_id\).*freshness\.checkpoint\(entitlement\.license_id\)/s);assert.doesNotMatch(main,/else\s*\{\s*freshness\.checkpoint/);});
test('no local DB-only legacy authorization bootstrap surface exists',()=>{const root=path.resolve(__dirname,'..'),backend=path.resolve(root,'../src/backend');const sources=[main,...['startup-verdict.js','trial-store.js','package.json'].map(x=>fs.readFileSync(path.join(root,x),'utf8')),...['desktop/routes.py','desktop/startup_verdict.py','desktop/mutation_gate.py'].map(x=>fs.readFileSync(path.join(backend,x),'utf8'))].join('\n');for(const forbidden of ['GROWTHMAP_LEGACY_BOOTSTRAP','authenticated_legacy_bootstrap','/api/desktop/legacy-free/start','legacy-free-bootstrap'])assert.doesNotMatch(sources,new RegExp(forbidden));assert.equal(fs.existsSync(path.join(root,'legacy-free-bootstrap.js')),false);assert.equal(fs.existsSync(path.join(root,'tests','legacy-free-bootstrap.test.js')),false);assert.match(sources,/prior_installation_evidence/);});

test('release workflows pin actions and ASAR verification is repository-local and fail-closed',()=>{
 const workflows=fs.readdirSync(path.resolve(__dirname,'../../.github/workflows')).filter(x=>x.endsWith('.yml'));
 for(const file of workflows){const source=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows',file),'utf8').replace(/\r\n/g,'\n');for(const match of source.matchAll(/uses:\s*([^\s#]+)/g)){assert.match(match[1],/@[0-9a-f]{40}$/,`${file} has floating action ${match[1]}`);assert.match(source.slice(match.index,source.indexOf('\n',match.index)),/# v\d+$/,`${file} action pin lacks version comment`);}}
 const crlfFixture='uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4\r\n';const normalizedFixture=crlfFixture.replace(/\r\n/g,'\n');const fixtureMatch=[...normalizedFixture.matchAll(/uses:\s*([^\s#]+)/g)][0];assert.match(normalizedFixture.slice(fixtureMatch.index,normalizedFixture.indexOf('\n',fixtureMatch.index)),/# v\d+$/);
 const resolver=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/scripts/resolve-local-asar.ps1'),'utf8');assert.match(resolver,/PSVersionTable\.PSVersion\.Major -lt 7/);assert.match(resolver,/desktop\/package-lock\.json/);assert.match(resolver,/ConvertFrom-Json -AsHashtable/);assert.match(resolver,/\$lock\['packages'\]\[''\]\['devDependencies'\]\['@electron\/asar'\]/);assert.doesNotMatch(resolver,/\$lock\.packages\.''/);assert.match(resolver,/Join-Path \$nodeModulesRoot '@electron\/asar'/);assert.match(resolver,/Join-Path \$expectedPackageRoot 'package\.json'/);assert.match(resolver,/declaredVersion -cne '4\.0\.1'/);assert.match(resolver,/lockedVersion -cne \$declaredVersion/);assert.match(resolver,/installed\.version -cne \$lockedVersion/);assert.match(resolver,/IsPathFullyQualified\(\$rawBin\)/);assert.match(resolver,/rawBin -match/);assert.match(resolver,/without traversal/);assert.match(resolver,/StartsWith\('\.\/'\)/);assert.match(resolver,/normalizedBin -cne 'bin\/asar\.mjs'/);assert.match(resolver,/expectedPackageRoot/);assert.match(resolver,/nodeModulesRoot/);
 for(const file of ['verify-production-asar.ps1','verify-production-unsigned-package.ps1','verify-gift-staging-package.ps1']){const source=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/scripts',file),'utf8');assert.doesNotMatch(source,/npx(?:\.cmd)?\s+--yes/);assert.match(source,/resolve-local-asar\.ps1/);assert.match(source,/& node \$asarCli/);assert.match(source,/\$LASTEXITCODE -ne 0/);}
});
test('R29 candidate metadata remains superseded history and is not invoked by R39',()=>{
 const manifest=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../release/windows-r29-candidate.json'),'utf8')),workflow=fs.readFileSync(path.resolve(__dirname,'../../.github/workflows/growthmap-windows-production-personal-v1.yml'),'utf8');assert.equal(manifest.candidate,'Windows R29');assert.equal(manifest.source.baseCommit,'e57c3b1a8eed5d79248d8f47d647231ae53e9e4f');assert.equal(manifest.source.tag,null);assert.equal(manifest.source.release,null);assert.doesNotMatch(workflow,/verify-windows-r29-candidate/);assert.match(workflow,/if-no-files-found: ignore/);
});

test('installed ASAR lock/bin normalization and containment matches PowerShell resolver contract',()=>{
 const root=path.resolve(__dirname,'..'),nodeModules=fs.realpathSync(path.join(root,'node_modules')),expectedPackage=path.resolve(nodeModules,'@electron','asar'),packageRoot=fs.realpathSync(path.join(root,'node_modules','@electron','asar')),metadata=JSON.parse(fs.readFileSync(path.join(packageRoot,'package.json'),'utf8')),lock=JSON.parse(fs.readFileSync(path.join(root,'package-lock.json'),'utf8'));
 assert.equal(packageRoot,expectedPackage);assert.ok(packageRoot.startsWith(nodeModules+path.sep));assert.equal(lock.packages[''].devDependencies['@electron/asar'],'4.0.1');assert.equal(lock.packages['node_modules/@electron/asar'].version,'4.0.1');assert.equal(metadata.version,'4.0.1');assert.ok(lock.packages['node_modules/@electron/asar'].integrity);
 const raw=metadata.bin.asar;assert.equal(path.isAbsolute(raw),false);assert.equal(raw.split(/[\\/]/).includes('..'),false);let normalized=raw.replace(/\\/g,'/');if(normalized.startsWith('./'))normalized=normalized.slice(2);assert.equal(normalized,'bin/asar.mjs');const entry=fs.realpathSync(path.resolve(packageRoot,normalized));assert.ok(entry.startsWith(packageRoot+path.sep));
 for(const rejected of ['/bin/asar.mjs','../bin/asar.mjs','bin/../asar.mjs','././bin/asar.mjs']){assert.ok(path.isAbsolute(rejected)||rejected.split(/[\\/]/).includes('..')||(()=>{let value=rejected.replace(/\\/g,'/');if(value.startsWith('./'))value=value.slice(2);return value!=='bin/asar.mjs'})());}
});

test('R39 release chain binds exact source closure, lazy replacement policy, and real-main gates',()=>{
 const root=path.resolve(__dirname,'../..'),workflow=fs.readFileSync(path.join(root,'.github/workflows/growthmap-windows-production-personal-v1.yml'),'utf8'),verifier=fs.readFileSync(path.join(root,'release/verify-windows-r39-candidate.cjs'),'utf8'),manifest=JSON.parse(fs.readFileSync(path.join(root,'release/windows-r39-candidate.json'),'utf8'));
 assert.equal(manifest.candidate,'Windows R39');assert.equal(manifest.schemaVersion,2);assert.equal(manifest.source.reviewBaseHead,'89821bf1e5d1a293a8b588d3fdd8b2fe09c83c35');assert.match(manifest.source.candidateDelta,/candidate commit atop reviewBaseHead/);assert.match(manifest.source.candidateDelta,/CI github\.sha/);assert.equal(manifest.source.tag,null);assert.equal(manifest.source.release,null);
 assert.match(workflow,/node release\/verify-windows-r39-candidate\.cjs/);assert.doesNotMatch(workflow,/verify-windows-r29-candidate/);
 for(const file of ['windows-native-broker.test.js','windows-native-evidence.test.js','windows-native-replacement.test.js','windows-startup-recovery.test.js','database-manager-windows-preflight.test.js','windows-recovery-barrier-acceptance.js','windows-r39-manager-acceptance.js']){assert(fs.existsSync(path.join(root,'desktop/tests',file)),file);assert.ok(workflow.includes(file),file);}for(const runtimeGate of ['windows-r311-broker-gate.js','windows-r312-security-matrix.js','windows-r313-security-matrix.js','windows-r316-startup-acceptance.js','windows-r318-hard-exit-acceptance.js','windows-r39-broker-smoke.js','windows-r39-acceptance.js'])assert.equal(workflow.includes(runtimeGate),false,runtimeGate);assert.match(workflow,/Windows replacement fail-closed policy acceptance/);
 const policyStep=workflow.slice(workflow.indexOf('      - name: Windows replacement fail-closed policy acceptance'),workflow.indexOf('      - name: Build isolated non-shipped R39 E2E package'));const policyCommands=['node --test tests/windows-native-broker.test.js tests/windows-native-evidence.test.js tests/windows-native-replacement.test.js tests/windows-startup-recovery.test.js tests/database-manager-windows-preflight.test.js','node tests/windows-recovery-barrier-acceptance.js','node tests/windows-r39-manager-acceptance.js'],policyPositions=policyCommands.map(command=>policyStep.indexOf(command));assert(policyPositions.every(position=>position>=0));assert.deepEqual(policyPositions,[...policyPositions].sort((a,b)=>a-b));assert.equal((workflow.match(/node tests\/windows-r39-manager-acceptance\.js/g)||[]).length,1);assert.match(policyStep,/timeout-minutes: 8/);assert.match(policyStep,/PYTHONUTF8: '1'/);assert.match(policyStep,/Windows R39 manager acceptance failed with exit \$LASTEXITCODE/);
 for(const command of ['npm run dist:win:e2e','npm run renderer:e2e'])assert.ok(workflow.includes(command));assert.match(workflow,/Delete isolated E2E package before production packaging/);assert.ok(workflow.indexOf('npm run renderer:e2e')<workflow.indexOf('Build exact unsigned commercial Windows package'));
 assert.match(workflow,/R39 packaged renderer and real-main lifecycle E2E[\s\S]{0,100}timeout-minutes: 11/);assert.doesNotMatch(workflow,/r39-native-\*\.log/);assert.match(workflow,/growthmap-r39-renderer\.png/);
 assert.match(verifier,/--review/);assert.match(verifier,/clean committed checkout/);assert.match(verifier,/Untracked or newly tracked release input is not pinned/);assert.match(verifier,/Missing release input/);assert.match(verifier,/Stale release input pin/);
});
test('frontend desktop declaration includes preload revocation import exactly',()=>{const declaration=fs.readFileSync(path.resolve(__dirname,'../../src/frontend/src/desktop.d.ts'),'utf8');assert.match(preload,/revocation:Object\.freeze\(\{import:\(\)=>ipcRenderer\.invoke\('revocation:import'\)\}\)/);assert.equal((declaration.match(/readonly revocation: \{ import\(\):Promise<unknown \| null> \}/g)||[]).length,1);});
