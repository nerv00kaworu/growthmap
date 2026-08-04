import test from "node:test";
import assert from "node:assert/strict";
import {freshNodeHistoryView,loadNodeHistory,NodeHistoryRequestCoordinator,visibleNodeHistoryView} from "./node-history-loader";

type Deferred<T>={promise:Promise<T>;resolve:(value:T)=>void;reject:(error:unknown)=>void};
function deferred<T>():Deferred<T>{let resolve!:(value:T)=>void,reject!:(error:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject};}
type View={history:string[];readbacks:string[];show:boolean;unavailable:boolean;error:string|null;loading:boolean};
function callbacks(view:View){return {onHistory:(history:string[])=>{view.history=history;view.show=true},onActivity:(activity:{readbacks:string[]})=>{view.readbacks=activity.readbacks},onUnavailable:()=>{view.readbacks=[];view.unavailable=true},onError:(error:unknown)=>{view.error=String(error)},onSettled:()=>{view.loading=false}};}

test("render-time guard hides state tagged for a previous node before effects run",()=>{
 const old={...freshNodeHistoryView<string,string>("project:A"),history:["A history"],readbacks:["A trace"],show:true,loading:true,error:"A error",traceUnavailable:true};
 assert.equal(visibleNodeHistoryView(old,"project:A"),old);
 assert.deepEqual(visibleNodeHistoryView(old,"project:B"),freshNodeHistoryView<string,string>("project:B"));
});

test("selection change invalidates pending history and activity transitions",async()=>{
 const oldHistory=deferred<string[]>(),oldActivity=deferred<{readbacks:string[]}>();
 const view:View={history:[],readbacks:[],show:false,unavailable:false,error:null,loading:true};
 const coordinator=new NodeHistoryRequestCoordinator("project:old");
 const oldLoad=loadNodeHistory(coordinator,"project:old",()=>oldHistory.promise,()=>oldActivity.promise,callbacks(view));
 coordinator.select("project:new");Object.assign(view,{history:[],readbacks:[],show:false,unavailable:false,error:null,loading:false});
 oldHistory.resolve(["old history"]);await oldLoad;
 assert.deepEqual(view,{history:[],readbacks:[],show:false,unavailable:false,error:null,loading:false});
});

test("selection change after history but before activity prevents old readback overwrite",async()=>{
 const activity=deferred<{readbacks:string[]}>();
 const view:View={history:[],readbacks:[],show:false,unavailable:false,error:null,loading:true};
 const coordinator=new NodeHistoryRequestCoordinator("project:old");
 const oldLoad=loadNodeHistory(coordinator,"project:old",async()=>["old history"],()=>activity.promise,callbacks(view));
 await Promise.resolve();assert.deepEqual(view.history,["old history"]);
 coordinator.select("project:new");Object.assign(view,{history:[],readbacks:[],show:false,unavailable:false,error:null,loading:false});
 activity.resolve({readbacks:["old trace"]});await oldLoad;
 assert.deepEqual(view,{history:[],readbacks:[],show:false,unavailable:false,error:null,loading:false});
});

test("403 activity preserves ordinary history and reports unavailable trace",async()=>{
 const view:View={history:[],readbacks:[],show:false,unavailable:false,error:null,loading:true};
 const coordinator=new NodeHistoryRequestCoordinator("project:node");
 await loadNodeHistory(coordinator,"project:node",async()=>["normal history"],async()=>{throw {status:403}},callbacks(view));
 assert.deepEqual(view,{history:["normal history"],readbacks:[],show:true,unavailable:true,error:null,loading:false});
});
