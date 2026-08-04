import {permanentRedirect} from 'next/navigation';
export default async function ProductAlias({params}:{params:Promise<{locale:string}>}){permanentRedirect(`/${(await params).locale}/ai-neutral`)}
