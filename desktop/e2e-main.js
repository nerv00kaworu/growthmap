'use strict';
// Test-package-only entrypoint. package.json production files excludes this file.
if(process.env.CI!=='true'||process.env.GROWTHMAP_DESKTOP_E2E!=='1')throw new Error('E2E test package is CI-only');
const commercialModule=require.resolve('./commercial-config');require(commercialModule);require.cache[commercialModule].exports={...require.cache[commercialModule].exports,loadCommercialConfig:require('./e2e-commercial-config').loadE2ECommercialConfig};
const fs=require('node:fs'),path=require('node:path'),{app,dialog}=require('electron'),fixture=process.env.GROWTHMAP_E2E_IMPORT_PATH;
const diagnosticPath=process.env.GROWTHMAP_E2E_DIAGNOSTIC_PATH,userData=process.env.GROWTHMAP_E2E_USER_DATA;
function phase(name){
 const line=`${new Date().toISOString()} pid=${process.pid} ${name}\n`;
 try{if(diagnosticPath)fs.appendFileSync(path.resolve(diagnosticPath),line,{encoding:'utf8',mode:0o600});}catch{}
 process.stdout.write(`[e2e-main] ${line}`);
}
phase('entrypoint-loaded');
// CDP is deliberately enabled only by renderer-e2e.js's direct executable switch.
// A CLI switch is consumed by Chromium before this packaged bootstrap executes.
const debugSwitch=process.argv.find(value=>value.startsWith('--remote-debugging-port='));
if(!debugSwitch)throw new Error('E2E debug CLI switch missing');
phase('command-line-switch-installed');
app.once('ready',()=>phase('app-ready'));
if(!fixture||!userData)throw new Error('E2E fixture or profile missing');
const relative=path.relative(path.resolve(userData),path.resolve(fixture));
if(relative===''||(!relative.startsWith('..'+path.sep)&&relative!=='..')||path.isAbsolute(relative))throw new Error('E2E import fixture must be outside userData');
const original=dialog.showOpenDialog.bind(dialog);
dialog.showOpenDialog=async(window,options)=>options?.filters?.some(x=>x.extensions?.includes('db'))?{canceled:false,filePaths:[fixture]}:original(window,options);
phase('main-required');
require('./main');
app.on('browser-window-created',(_event,window)=>window.webContents.on('did-finish-load',()=>window.webContents.executeJavaScript(`document.documentElement.dataset.growthmapRendererReady='true'`).catch(()=>{})));
