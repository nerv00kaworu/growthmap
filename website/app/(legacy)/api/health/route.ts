import {NextResponse} from 'next/server';export function GET(){return NextResponse.json({status:'ok',service:'growthmap-website'},{headers:{'Cache-Control':'no-store'}})}
