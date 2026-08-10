import {NextRequest,NextResponse} from 'next/server';
export function proxy(request:NextRequest){const locale=request.nextUrl.pathname.match(/^\/(zh-TW|zh-CN|en)(?:\/|$)/)?.[1]??'zh-TW';const headers=new Headers(request.headers);headers.set('x-growthmap-locale',locale);return NextResponse.next({request:{headers}})}
export const config={matcher:['/((?!_next/static|_next/image|favicon.ico|media/|og/).*)']};
