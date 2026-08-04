import type { NextConfig } from 'next';
const securityHeaders = [
 {key:'Content-Security-Policy',value:"default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; upgrade-insecure-requests"},
 {key:'X-Frame-Options',value:'DENY'}, {key:'X-Content-Type-Options',value:'nosniff'},
 {key:'Referrer-Policy',value:'strict-origin-when-cross-origin'}, {key:'Permissions-Policy',value:'camera=(), microphone=(), geolocation=()'}
];
const sensitiveHeaders=[...securityHeaders,{key:'Cache-Control',value:'no-store, max-age=0'},{key:'Referrer-Policy',value:'no-referrer'}];
const config: NextConfig = { output: 'standalone', turbopack: { root: process.cwd() }, async headers(){return [{source:'/:path*',headers:securityHeaders},{source:'/(buy|order/:path*)',headers:sensitiveHeaders},{source:'/:locale(zh-TW|zh-CN|en)/(buy|order/:path*)',headers:sensitiveHeaders}]}};
export default config;
