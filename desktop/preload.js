'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('growthmapDesktop',Object.freeze({
 isDesktop:true,
 agentPortControl:true,
 agentPort:Object.freeze({list:p=>ipcRenderer.invoke('agent-port:list',p),create:d=>ipcRenderer.invoke('agent-port:create',d),revoke:id=>ipcRenderer.invoke('agent-port:revoke',id),activity:(p,t)=>ipcRenderer.invoke('agent-port:activity',p,t),review:(id,d,n)=>ipcRenderer.invoke('agent-port:review',id,d,n)}),
 agentAccess:Object.freeze({status:()=>ipcRenderer.invoke('agent-access:status'),enable:o=>ipcRenderer.invoke('agent-access:enable',o),disable:()=>ipcRenderer.invoke('agent-access:disable'),config:()=>ipcRenderer.invoke('agent-access:config'),copy:()=>ipcRenderer.invoke('agent-access:copy'),download:()=>ipcRenderer.invoke('agent-access:download'),test:()=>ipcRenderer.invoke('agent-access:test'),regenerate:()=>ipcRenderer.invoke('agent-access:regenerate')}),
 secrets:Object.freeze({has:id=>ipcRenderer.invoke('secrets:has',id),set:(id,value)=>ipcRenderer.invoke('secrets:set',id,value),delete:id=>ipcRenderer.invoke('secrets:delete',id)}),
 license:Object.freeze({import:()=>ipcRenderer.invoke('license:import'),activate:key=>ipcRenderer.invoke('license:activate',key)}),
 revocation:Object.freeze({import:()=>ipcRenderer.invoke('revocation:import')}),
 purchase:Object.freeze({open:()=>ipcRenderer.invoke('purchase:open'),publicConfig:()=>ipcRenderer.invoke('commercial:public')}),
 support:Object.freeze({open:()=>ipcRenderer.invoke('commercial:support-open')}),
 entitlement:Object.freeze({onChanged:callback=>{if(typeof callback!=='function')throw new TypeError('callback must be a function');const listener=()=>callback();ipcRenderer.on('desktop:entitlement-changed',listener);return()=>ipcRenderer.removeListener('desktop:entitlement-changed',listener);}}),
 updates:Object.freeze({check:()=>ipcRenderer.invoke('updates:check')}),
 database:Object.freeze({status:()=>ipcRenderer.invoke('database:status'),chooseWorkspace:()=>ipcRenderer.invoke('database:choose-workspace'),import:()=>ipcRenderer.invoke('database:import'),backup:()=>ipcRenderer.invoke('database:backup'),listBackups:()=>ipcRenderer.invoke('database:list-backups'),restore:id=>ipcRenderer.invoke('database:restore',id),revealFolder:()=>ipcRenderer.invoke('database:reveal')})
}));
