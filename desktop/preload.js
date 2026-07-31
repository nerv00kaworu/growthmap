'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('growthmapDesktop',Object.freeze({
 isDesktop:true,
 agentPortControl:true,
 secrets:Object.freeze({has:id=>ipcRenderer.invoke('secrets:has',id),set:(id,value)=>ipcRenderer.invoke('secrets:set',id,value),delete:id=>ipcRenderer.invoke('secrets:delete',id)}),
 license:Object.freeze({import:()=>ipcRenderer.invoke('license:import')}),
 revocation:Object.freeze({import:()=>ipcRenderer.invoke('revocation:import')}),
 purchase:Object.freeze({info:()=>ipcRenderer.invoke('purchase:info'),copyBaseAddress:()=>ipcRenderer.invoke('purchase:copy-base-address'),open:rail=>ipcRenderer.invoke('purchase:open',rail)}),
 entitlement:Object.freeze({onChanged:callback=>{if(typeof callback!=='function')throw new TypeError('callback must be a function');const listener=()=>callback();ipcRenderer.on('desktop:entitlement-changed',listener);return()=>ipcRenderer.removeListener('desktop:entitlement-changed',listener);}}),
 updates:Object.freeze({check:()=>ipcRenderer.invoke('updates:check')}),
 database:Object.freeze({status:()=>ipcRenderer.invoke('database:status'),import:()=>ipcRenderer.invoke('database:import'),backup:()=>ipcRenderer.invoke('database:backup'),listBackups:()=>ipcRenderer.invoke('database:list-backups'),restore:id=>ipcRenderer.invoke('database:restore',id),revealFolder:()=>ipcRenderer.invoke('database:reveal')})
}));
