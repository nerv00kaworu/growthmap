import {permanentRedirect} from 'next/navigation';
export default async function AgentsAlias({params}:{params:Promise<{locale:string}>}){permanentRedirect(`/${(await params).locale}/showcase`)}
