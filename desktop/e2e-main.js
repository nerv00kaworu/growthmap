'use strict';
// Test-package-only entrypoint. package.json production files excludes this file.
if(process.env.CI!=='true'||process.env.GROWTHMAP_DESKTOP_E2E!=='1')throw new Error('E2E test package is CI-only');
const {app,dialog}=require('electron'),fixture=process.env.GROWTHMAP_E2E_IMPORT_PATH;
if(process.env.GROWTHMAP_E2E_DEBUG_PORT)app.commandLine.appendSwitch('remote-debugging-port',process.env.GROWTHMAP_E2E_DEBUG_PORT);
if(!fixture)throw new Error('E2E fixture missing');
const original=dialog.showOpenDialog.bind(dialog);
dialog.showOpenDialog=async(window,options)=>options?.filters?.some(x=>x.extensions?.includes('db'))?{canceled:false,filePaths:[fixture]}:original(window,options);
require('./main');
app.on('browser-window-created',(_event,window)=>window.webContents.on('did-finish-load',()=>window.webContents.executeJavaScript(`document.documentElement.dataset.growthmapRendererReady='true'`).catch(()=>{})));
