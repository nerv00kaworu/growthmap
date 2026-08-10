import type { NextConfig } from 'next';
const securityHeaders = [
 {key:'Content-Security-Policy',value:"default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; upgrade-insecure-requests"},
 {key:'X-Frame-Options',value:'DENY'}, {key:'X-Content-Type-Options',value:'nosniff'},
 {key:'Referrer-Policy',value:'strict-origin-when-cross-origin'}, {key:'Permissions-Policy',value:'camera=(), microphone=(), geolocation=()'}
];
const htmlHeaders=[...securityHeaders,{key:'Cache-Control',value:'public, max-age=0, s-maxage=3600, stale-while-revalidate=86400'}];
const sensitiveHeaders=[...securityHeaders,{key:'Cache-Control',value:'no-store, max-age=0'},{key:'Referrer-Policy',value:'no-referrer'}];
const immutableHeaders=[...securityHeaders,{key:'Cache-Control',value:'public, max-age=31536000, immutable'}];
const config: NextConfig = { experimental:{globalNotFound:true}, output: 'standalone', turbopack: { root: process.cwd() }, async headers(){return [
 {source:'/:path*',headers:htmlHeaders},
 {source:'/_next/static/:path*',headers:immutableHeaders},
 {source:'/(media|og)/:path*',headers:[...securityHeaders,{key:'Cache-Control',value:'public, max-age=3600, must-revalidate'}]},
 {source:'/:file(favicon.png|apple-touch-icon.png|icon-192.png|icon-512.png|icon.svg|manifest.webmanifest)',headers:[...securityHeaders,{key:'Cache-Control',value:'public, max-age=3600, must-revalidate'}]},
 {source:'/(buy|download|status|privacy|terms|refund|order/:path*|api/:path*)',headers:sensitiveHeaders},
 {source:'/:locale(zh-TW|zh-CN|en)/(buy|download|status|privacy|terms|refund|order/:path*)',headers:sensitiveHeaders}
 ]}};
export default config;
