export type DatabaseOperationKind="backup"|"import"|"restore"|"workspace";
export type DatabasePresentation="workspace"|"backup"|"replacement-safe"|"cleanup-pending"|"replacement-unknown"|"failure"|null;
export interface DatabaseWorkspaceViewState { presentation:DatabasePresentation; cleanupBanner:boolean }
export const initialDatabaseWorkspaceViewState:DatabaseWorkspaceViewState={presentation:null,cleanupBanner:false};
export function databaseWorkspaceTransition(state:DatabaseWorkspaceViewState,event:
 |{type:"result";kind:DatabaseOperationKind;result:unknown}
 |{type:"status";cleanupPending:boolean}
 |{type:"failure"}):DatabaseWorkspaceViewState{
 if(event.type==="status")return {...state,cleanupBanner:event.cleanupPending};
 if(event.type==="failure")return {...state,presentation:"failure"};
 const value=event.result as {cleanup?:unknown}|null;
 const hasCleanup=Boolean(value&&typeof value==="object"&&Object.prototype.hasOwnProperty.call(value,"cleanup")),cleanup=hasCleanup?value!.cleanup:undefined;
 let replacement:DatabasePresentation="replacement-safe";
 if(cleanup!==undefined&&cleanup!==null){const keys=typeof cleanup==="object"&&!Array.isArray(cleanup)?Object.keys(cleanup as object).sort():[];replacement=keys.length===2&&keys[0]==="pending"&&keys[1]==="stage"&&(cleanup as {pending?:unknown}).pending===true&&(cleanup as {stage?:unknown}).stage==="committed-old-cleanup"?"cleanup-pending":"replacement-unknown";}
 return {...state,presentation:event.kind==="workspace"?"workspace":event.kind==="backup"?"backup":replacement};
}
