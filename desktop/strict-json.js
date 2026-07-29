'use strict';
// Scan object keys before JSON.parse can collapse them. Reject exact duplicates and
// case-collisions at every nesting level, then delegate value construction to JSON.parse.
function parseStrictJson(raw){
 if(typeof raw!=='string')throw Error('JSON input must be text');let i=0;const ws=()=>{while(/[\x20\t\r\n]/.test(raw[i]||''))i++;};
 function str(){const start=i++;if(raw[start]!=='"')throw Error('Expected string');for(;i<raw.length;i++){if(raw[i]==='\\'){i++;continue;}if(raw[i]==='"'){i++;return JSON.parse(raw.slice(start,i));}if(raw.charCodeAt(i)<32)throw Error('Invalid JSON string');}throw Error('Unterminated string');}
 function value(){ws();if(raw[i]==='{')return object();if(raw[i]==='[')return array();if(raw[i]==='"'){str();return;}const m=/^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(raw.slice(i));if(!m)throw Error('Invalid JSON value');i+=m[0].length;}
 function object(){i++;ws();const keys=new Set(),folded=new Set();if(raw[i]==='}'){i++;return;}for(;;){ws();const key=str(),fold=key.toLowerCase().normalize('NFC');if(keys.has(key))throw Error('Duplicate JSON key');if(folded.has(fold))throw Error('Case-colliding JSON key');keys.add(key);folded.add(fold);ws();if(raw[i++]!==':')throw Error('Expected colon');value();ws();if(raw[i]==='}'){i++;return;}if(raw[i++]!==',')throw Error('Expected comma');}}
 function array(){i++;ws();if(raw[i]===']'){i++;return;}for(;;){value();ws();if(raw[i]===']'){i++;return;}if(raw[i++]!==',')throw Error('Expected comma');}}
 value();ws();if(i!==raw.length)throw Error('Trailing JSON input');return JSON.parse(raw);
}
module.exports={parseStrictJson};
