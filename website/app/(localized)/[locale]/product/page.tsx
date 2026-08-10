import {permanentRedirect} from 'next/navigation';export default async function P({params}:{params:Promise<{locale:string}>}){permanentRedirect(`/${(await params).locale}/features`)}
