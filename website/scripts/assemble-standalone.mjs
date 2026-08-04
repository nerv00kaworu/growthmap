import {cp,rm,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';

const root=process.cwd();
const source=resolve(root,'.next/static');
const target=resolve(root,'.next/standalone/.next/static');
await rm(target,{recursive:true,force:true});
await mkdir(resolve(root,'.next/standalone/.next'),{recursive:true});
await cp(source,target,{recursive:true});
console.log('assembled standalone static assets');
