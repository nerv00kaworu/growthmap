import type { ProviderConfig } from "./types";
import type { LLMProviderType } from "./llm-provider";
import { msg } from "@/i18n/ui";

export const MAX_MODEL_NAME = 128;
export type AILocale = "zh-TW" | "zh-CN" | "en";
export interface AIProviderIdentity { providerId:string; providerType:LLMProviderType; model:string; revision:number;selectionRevision:number }
export function providerIdentity(p:ProviderConfig):AIProviderIdentity{return{providerId:p.id,providerType:p.provider_type as LLMProviderType,model:p.model_name,revision:p.revision,selectionRevision:p.selection_revision ?? 1}}
export function sameProviderIdentity(a:AIProviderIdentity|null,b:AIProviderIdentity|null){return!!(a&&b&&a.providerId===b.providerId&&a.providerType===b.providerType&&a.model===b.model&&a.revision===b.revision&&a.selectionRevision===b.selectionRevision)}
export function validateModelName(value:string):{ok:true;value:string}|{ok:false;reason:"empty"|"too_long"}{const v=value.trim();return!v?{ok:false,reason:"empty"}:v.length>MAX_MODEL_NAME?{ok:false,reason:"too_long"}:{ok:true,value:v}}
export function diagnosticMessage(locale:AILocale,code?:string){const m=(tw:string,cn:string,en:string)=>msg(locale,{"zh-TW":tw,"zh-CN":cn,en});switch(code){case"LLM_PROFILE_CHANGED":return m("AI 設定檔已變更，請重新檢查後再試。","AI 配置已更改，请重新检查后再试。","The AI profile changed. Review it and retry.");case"LLM_CONFIGURATION_ERROR":return m("所選 AI 設定檔無法使用，請檢查安全儲存設定。","所选 AI 配置无法使用，请检查安全存储设置。","The selected AI profile is unavailable. Check its secure-storage configuration.");case"LLM_AUTH_FAILED":return m("AI 提供者拒絕憑證，請重新綁定金鑰。","AI 提供商拒绝凭据，请重新绑定密钥。","The AI provider rejected its credentials. Rebind the key.");case"LLM_RATE_LIMITED":return m("AI 提供者已達速率限制，請稍後重試。","AI 提供商已达到速率限制，请稍后重试。","The AI provider rate limit was reached. Wait and retry.");case"LLM_INVALID_RESPONSE":return m("AI 回應格式無法驗證，請重試。","AI 响应格式无法验证，请重试。","The AI response could not be validated. Please retry.");case"LLM_TIMEOUT":return m("AI 提供者逾時，請重試。","AI 提供商超时，请重试。","The AI provider timed out. Please retry.");default:return m("AI 提供者暫時無法使用，請重試。","AI 提供商暂时不可用，请重试。","The AI provider is temporarily unavailable. Please retry.")}}

export type PanelTestState={kind:"testing"|"success"|"error";elapsed:number;message:string;code?:string;status?:number;requestId?:string};
export type AIPanelState={profiles:ProviderConfig[];profileState:"loading"|"ready"|"error";saving:boolean;modelError:string|null;test:PanelTestState|null;copyMessage:string|null;generationError:string|null};
export type AIPanelDeps={
 listProviders:()=>Promise<ProviderConfig[]>; updateModel:(id:string,model:string)=>Promise<ProviderConfig>; testConnection:(id:string,revision:number,selectionRevision:number)=>Promise<{code?:string;request_id?:string}>;
 confirm:(text:string)=>boolean; copy:(text:string)=>Promise<void>; now:()=>number; locale:()=>AILocale; currentIdentity:()=>AIProviderIdentity|null;
 onSaved:(p:ProviderConfig)=>void; onListed?:(profiles:ProviderConfig[])=>void; onInvalidate:()=>void;
};
function panelMessage(locale:AILocale,key:"save_error"|"test_confirm"|"test_success"|"copy_success"|"copy_error"|"generation_changed"){const m=(tw:string,cn:string,en:string)=>msg(locale,{"zh-TW":tw,"zh-CN":cn,en});switch(key){case"save_error":return m("模型儲存失敗，舊模型仍在使用。","模型保存失败，旧模型仍在使用。","Model save failed; the previous model remains active.");case"test_confirm":return m("測試會送出小型 completion，可能消耗額度。繼續？","测试会发送小型 completion，可能消耗额度。继续？","The test sends a small completion and may consume quota. Continue?");case"test_success":return m("連線成功。","连接成功。","Connection succeeded.");case"copy_success":return m("已複製請求 ID。","已复制请求 ID。","Request ID copied.");case"copy_error":return m("無法複製請求 ID。","无法复制请求 ID。","Could not copy request ID.");case"generation_changed":return m("LLM 設定檔已變更；已取消這次操作，請確認設定後重試。","LLM 配置已更改；本次操作已取消，请确认设置后重试。","The LLM profile changed; this action was cancelled. Verify the profile and retry.")}}
export type GenerateArgs={actionLabel:string;profileName:string;identity:AIProviderIdentity;dispatch:()=>void;savedIdentity:()=>AIProviderIdentity|null};
let profileCache:ReadonlyArray<ProviderConfig>=[];
export function resetAIPanelProfileCacheForTests(){profileCache=[]}
export function confirmationText(locale:AILocale,action:string,identity:AIProviderIdentity,name:string){const m=(tw:string,cn:string,en:string)=>msg(locale,{"zh-TW":tw,"zh-CN":cn,en});return`${m("設定檔","配置","Profile")}: ${name} (${identity.providerId})\n${m("類型","类型","Type")}: ${identity.providerType}\n${m("模型","模型","Model")}: ${identity.model}\n${m("版本","版本","Version")}: ${identity.revision} / selection ${identity.selectionRevision}\n\n${action} — ${m("可能消耗 API 額度，是否繼續？","可能消耗 API 配额，是否继续？","This may consume API quota. Continue?")}`}

/** Injectable orchestration authority used directly by NodeAI. Every async result
 * is generation- and exact-identity-owned; invalidate/unmount makes it inert. */
export function createAIPanelController(d:AIPanelDeps){
 let alive=true,listGen=0,saveGen=0,testGen=0,state:AIPanelState={profiles:[...profileCache],profileState:profileCache.length?"ready":"loading",saving:false,modelError:null,test:null,copyMessage:null,generationError:null};const listeners=new Set<()=>void>();
 const emit=(patch:Partial<AIPanelState>)=>{if(!alive)return;state={...state,...patch};listeners.forEach(f=>f())};
 const owns=(g:number,kind:"save"|"test",identity:AIProviderIdentity)=>alive&&g===(kind==="save"?saveGen:testGen)&&sameProviderIdentity(identity,d.currentIdentity());
 return {getSnapshot:()=>state,subscribe:(f:()=>void)=>{listeners.add(f);return()=>listeners.delete(f)},
  async list(){const g=++listGen;emit({profileState:state.profiles.length?"ready":"loading",test:null});try{const rows=(await d.listProviders()).filter(p=>p.enabled);if(alive&&g===listGen){profileCache=rows;emit({profiles:rows,profileState:"ready"});d.onListed?.(rows)}}catch{if(alive&&g===listGen)emit(state.profiles.length?{profileState:"ready"}:{profiles:[],profileState:"error"})}},
  async save(model:string){const identity=d.currentIdentity(),valid=validateModelName(model);if(!identity||!valid.ok||valid.value===identity.model||state.saving)return;const g=++saveGen;emit({saving:true,modelError:null,test:null});try{const p=await d.updateModel(identity.providerId,valid.value);if(owns(g,"save",identity)){emit({profiles:state.profiles.map(x=>x.id===p.id?p:x),saving:false});d.onSaved(p);d.onInvalidate()}}catch{if(owns(g,"save",identity))emit({saving:false,modelError:panelMessage(d.locale(),"save_error")})}finally{if(alive&&g===saveGen&&state.saving)emit({saving:false})}},
  async test(){const identity=d.currentIdentity();if(!identity||state.test?.kind==="testing")return;if(identity.providerType!=="mock"&&!d.confirm(panelMessage(d.locale(),"test_confirm")))return;if(!sameProviderIdentity(identity,d.currentIdentity()))return;const g=++testGen,started=d.now();emit({test:{kind:"testing",elapsed:0,message:"Testing…"}});try{const r=await d.testConnection(identity.providerId,identity.revision,identity.selectionRevision);if(owns(g,"test",identity))emit({test:{kind:"success",elapsed:d.now()-started,message:panelMessage(d.locale(),"test_success"),code:r.code,status:200,requestId:r.request_id}})}catch(e){if(owns(g,"test",identity)){const x=e as {code?:string;status?:number;requestId?:string};emit({test:{kind:"error",elapsed:d.now()-started,message:diagnosticMessage(d.locale(),x.code),code:x.code,status:x.status,requestId:x.requestId}})}}},
  generate(a:GenerateArgs){emit({generationError:null});if(a.identity.providerType!=="mock"&&!d.confirm(confirmationText(d.locale(),a.actionLabel,a.identity,a.profileName)))return false;if(!sameProviderIdentity(a.identity,a.savedIdentity())||!sameProviderIdentity(a.identity,d.currentIdentity())){emit({generationError:panelMessage(d.locale(),"generation_changed")});return false}a.dispatch();return true},
  async copy(id:string){try{await d.copy(id);emit({copyMessage:panelMessage(d.locale(),"copy_success")})}catch{emit({copyMessage:panelMessage(d.locale(),"copy_error")})}},
  invalidateOperations(){saveGen++;testGen++;emit({saving:false,test:null,modelError:null,generationError:null})},
  invalidate(){listGen++;saveGen++;testGen++;emit({saving:false,test:null,modelError:null,generationError:null})},
  activate(){alive=true},
  suspend(){alive=false;listGen++;saveGen++;testGen++},
  destroy(){alive=false;listGen++;saveGen++;testGen++;listeners.clear()}
 }}

// Retained small primitives are useful to other state machines and compatibility tests.
export class MonotonicOwner<T>{private generation=0;issue(value:T){return{generation:++this.generation,value}as const}invalidate(){this.generation++}owns(token:Readonly<{generation:number;value:T}>,equal:(a:T,b:T)=>boolean,current:T){return token.generation===this.generation&&equal(token.value,current)}}
export class LatestAsync<T>{private generation=0;begin(){return++this.generation}invalidate(){this.generation++}isCurrent(t:number){return t===this.generation}filterEnabled(t:number,rows:readonly T[],enabled:(r:T)=>boolean){return this.isCurrent(t)?rows.filter(enabled):null}}
export type SaveLatch=Readonly<{token:number;profileId:string}>|null;export function beginSave(p:SaveLatch,t:number,id:string):SaveLatch{return p?p:{token:t,profileId:id}}export function releaseSave(c:SaveLatch,t:number):SaveLatch{return c?.token===t?null:c}
