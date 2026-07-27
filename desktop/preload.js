'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('growthmapDesktop',Object.freeze({
 isDesktop:true,
 secrets:Object.freeze({has:id=>ipcRenderer.invoke('secrets:has',id),set:(id,value)=>ipcRenderer.invoke('secrets:set',id,value),delete:id=>ipcRenderer.invoke('secrets:delete',id)}),
 license:Object.freeze({import:()=>ipcRenderer.invoke('license:import')}),
 database:Object.freeze({status:()=>ipcRenderer.invoke('database:status'),import:()=>ipcRenderer.invoke('database:import'),backup:()=>ipcRenderer.invoke('database:backup'),listBackups:()=>ipcRenderer.invoke('database:list-backups'),restore:id=>ipcRenderer.invoke('database:restore',id),revealFolder:()=>ipcRenderer.invoke('database:reveal')})
}));
