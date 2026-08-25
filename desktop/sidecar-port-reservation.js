'use strict';
async function reserveDistinctPort(used,reserve){
 if(!(used instanceof Set)||typeof reserve!=='function')throw new TypeError('Distinct port reservation requires a Set and reserve function');
 for(let tryCount=0;tryCount<32;tryCount++){
  const value=await reserve();
  if(!used.has(value)){used.add(value);return value;}
 }
 throw new Error('Could not reserve a distinct sidecar retry port');
}
module.exports={reserveDistinctPort};
