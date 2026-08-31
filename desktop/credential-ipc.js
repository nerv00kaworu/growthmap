'use strict';
/** Register credential IPC against a live getter so lineage rotations are atomic. */
function registerCredentialIpc({ipcMain,guard,getStore}){
 const invoke=(event,method,args)=>{guard(event);return getStore()[method](...args)};
 ipcMain.handle('secrets:has',(e,id)=>invoke(e,'has',[id]));
 ipcMain.handle('secrets:set',(e,id,value)=>invoke(e,'set',[id,value]));
 ipcMain.handle('secrets:delete',(e,id)=>invoke(e,'delete',[id]));
 ipcMain.handle('secrets:recover',(e,id,revision,operation,value,operationId)=>invoke(e,'recover',operationId===undefined?[id,revision,operation,value]:[id,revision,operation,value,operationId]));
}
module.exports={registerCredentialIpc};
