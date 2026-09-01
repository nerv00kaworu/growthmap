export type SSEMessage={event:string;id:string;data:string;retry?:number};
export class SSEParser{
  private buffer="";
  push(chunk:string):SSEMessage[]{
    this.buffer+=chunk;if(new TextEncoder().encode(this.buffer).byteLength>16384){this.buffer="";return [];}const out:SSEMessage[]=[];
    for(;;){const match=/\r?\n\r?\n/.exec(this.buffer);if(!match)break;const raw=this.buffer.slice(0,match.index);this.buffer=this.buffer.slice(match.index+match[0].length);let event="message",id="",retry: number|undefined;const data:string[]=[];
      for(const line of raw.split(/\r?\n/)){if(!line||line.startsWith(":"))continue;const i=line.indexOf(":"),name=i<0?line:line.slice(0,i),value=i<0?"":line.slice(i+1).replace(/^ /,"");if(name==="event")event=value;else if(name==="id"&&!value.includes("\0"))id=value;else if(name==="data")data.push(value);else if(name==="retry"&&/^\d{1,8}$/.test(value)&&Number(value)>=1000&&Number(value)<=30000)retry=Number(value);}
      if(data.length)out.push({event,id,data:data.join("\n"),retry});
    }return out;
  }
}
const PROJECT_ID=/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;
const WAKE_KINDS=new Set(["graph", "canonical", "workspace"]);
export function parseReadyFrame(data:string):boolean{
  if(new TextEncoder().encode(data).byteLength>512)return false;
  try{const x=JSON.parse(data) as Record<string,unknown>;return x.schema===1&&Object.keys(x).length<=4;}catch{return false;}
}
export function parseCanonicalWake(data:string):{project_id:string;revision:number}|null{
  if(new TextEncoder().encode(data).byteLength>8192)return null;
  try { const x=JSON.parse(data) as Record<string,unknown>;
    if(x.schema!==1 || typeof x.kind!=="string" || !WAKE_KINDS.has(x.kind) || typeof x.project_id!=="string" || !PROJECT_ID.test(x.project_id) || !Number.isSafeInteger(x.revision) || Number(x.revision)<0 || (x.kind !== "workspace" && Number(x.revision) === 0)) return null;
    if ("cursor" in x && (typeof x.cursor!=="string" || x.cursor.length>256)) return null;
    return {project_id:x.project_id,revision:Number(x.revision)};
  } catch { return null; }
}
