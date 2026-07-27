'use strict';
const fs=require('node:fs');
const net=require('node:net');
const path=require('node:path');
const {spawn,spawnSync}=require('node:child_process');
const {chromium}=require('playwright-core');
if(process.platform!=='win32')throw new Error('Packaged renderer smoke must run on Windows');
if(process.env.CI!=='true')throw new Error('Renderer E2E debug transport is restricted to CI');
const root=path.resolve(__dirname,'..');
const executable=process.env.GROWTHMAP_PACKAGED_EXE||path.join(root,'dist','win-unpacked','GrowthMap.exe');
const screenshot=process.env.GROWTHMAP_E2E_SCREENSHOT||path.join(root,'artifacts','growthmap-renderer.png');
function port(){return new Promise((resolve,reject)=>{const s=net.createServer();s.once('error',reject);s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});}
function sleep(ms){return new Promise(r=>setTimeout(r,ms));}
(async()=>{
  if(!fs.existsSync(executable))throw new Error(`Packaged executable missing: ${executable}`);
  const debugPort=await port();
  const child=spawn(executable,[],{env:{...process.env,CI:'true',GROWTHMAP_DESKTOP_E2E:'1',GROWTHMAP_E2E_DEBUG_PORT:String(debugPort)},stdio:['ignore','pipe','pipe'],windowsHide:true});
  let output=''; child.stdout.on('data',x=>output+=x); child.stderr.on('data',x=>output+=x);
  let browser;
  try{
    const deadline=Date.now()+120000;
    while(Date.now()<deadline){
      if(child.exitCode!==null)throw new Error(`Packaged Electron exited early (${child.exitCode}): ${output.slice(-2000)}`);
      try{browser=await chromium.connectOverCDP(`http://127.0.0.1:${debugPort}`,{timeout:2000});break;}catch{await sleep(250);}
    }
    if(!browser)throw new Error(`Timed out connecting to packaged Electron renderer: ${output.slice(-2000)}`);
    let page;
    while(Date.now()<deadline&&!page){page=browser.contexts().flatMap(c=>c.pages()).find(p=>p.url().startsWith('http://127.0.0.1:'));if(!page)await sleep(250);}
    if(!page)throw new Error('Packaged Electron main window was not created');
    await page.waitForFunction(()=>document.documentElement.dataset.growthmapRendererReady==='true'&&document.querySelector('[data-testid="growthmap-title"]')&&document.querySelector('[data-testid="new-project-button"]')&&document.querySelector('[data-testid="entitlement-status"]'),null,{timeout:90000});
    const result=await page.evaluate(()=>({title:document.title,text:document.body.innerText.trim(),titleMarker:document.querySelector('[data-testid="growthmap-title"]')?.textContent||'',newProjectMarker:document.querySelector('[data-testid="new-project-button"]')?.textContent||'',entitlementMarker:document.querySelector('[data-testid="entitlement-status"]')?.textContent||'',body:{width:document.body.getBoundingClientRect().width,height:document.body.getBoundingClientRect().height,display:getComputedStyle(document.body).display,background:getComputedStyle(document.body).backgroundColor},styles:[...document.styleSheets].length}));
    if(result.title!=='GrowthMap'||!result.text||!result.titleMarker.includes('GrowthMap')||!result.newProjectMarker.includes('新專案')||!result.entitlementMarker.includes('Free · 0/2')||result.body.width<800||result.body.height<500||result.body.display==='none'||result.styles<1)throw new Error(`Renderer visual contract failed: ${JSON.stringify(result)}`);
    fs.mkdirSync(path.dirname(screenshot),{recursive:true}); await page.screenshot({path:screenshot,fullPage:true});
    if(!output.includes('GROWTHMAP_RENDERER_READY'))throw new Error('Packaged app did not emit renderer-ready marker');
    console.log(`Packaged Electron renderer smoke passed; screenshot=${screenshot}`);
  } finally {
    if(browser)await Promise.race([browser.close().catch(()=>{}),sleep(3000)]);
    if(child.exitCode===null){
      spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore',windowsHide:true,timeout:10000});
      child.kill();
    }
  }
})().then(()=>process.exit(0)).catch(e=>{console.error(e.stack||e);process.exit(1);});
