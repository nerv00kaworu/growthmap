'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {forbiddenPublicLiteralHost,strictCanonicalPublicHttpsOrigin,validatePurchasePortalUrl,purchasePortalTarget,purchaseTargetForArgs}=require('../purchase-portal');
const origin='https://pay.growthmap.test',base=`${origin}/buy`;
test('canonical public HTTPS origins reject noncanonical and private authorities',()=>{
 assert.equal(strictCanonicalPublicHttpsOrigin(origin),origin);
 assert.equal(strictCanonicalPublicHttpsOrigin('https://xn--bcher-kva.example'),'https://xn--bcher-kva.example');
 for(const value of ['https://PAY.growthmap.test','https://pay.growthmap.test:443','https://pay.growthmap.test.','https://bücher.example','https://pay.growthmap.test/extra','http://pay.growthmap.test','https://pay.growthmap.test?x','https://pay.growthmap.test#x','https://user@pay.growthmap.test','\nhttps://pay.growthmap.test'])assert.throws(()=>strictCanonicalPublicHttpsOrigin(value),value);
});
test('production payment authorities reject every IP literal, including normalized and special-purpose forms',()=>{
 for(const host of ['0.0.0.0','8.8.8.8','10.0.0.1','100.64.0.1','127.0.0.1','169.254.1.1','172.32.0.1','192.0.0.1','192.0.2.1','198.18.0.1','198.51.100.1','203.0.113.1','224.0.0.1','240.0.0.1','255.255.255.255','::','::1','100::1','2001:db8::1','2001:4860:4860::8888','fc00::1','fe80::1','fec0::1','ff00::1','::ffff:8.8.8.8','::ffff:10.0.0.1'])assert.equal(forbiddenPublicLiteralHost(host),true,host);
 for(const host of ['pay.growthmap.test','xn--bcher-kva.example'])assert.equal(forbiddenPublicLiteralHost(host),false,host);
 for(const value of ['https://8.8.8.8','https://100.64.0.1','https://192.0.2.1','https://198.18.0.1','https://203.0.113.1','https://224.0.0.1','https://240.0.0.1','https://127.1','https://2130706433','https://0177.0.0.1','https://0x7f000001','https://0','https://[2001:4860:4860::8888]','https://[2001:db8::1]','https://[ff00::1]','https://[::ffff:7f00:1]'])assert.throws(()=>strictCanonicalPublicHttpsOrigin(value),value);
});
test('reviewed purchase portal is an exact canonical query-free target',()=>{
 assert.equal(validatePurchasePortalUrl(base,origin),base);assert.equal(purchasePortalTarget(base,origin),base);
 assert.equal(validatePurchasePortalUrl('https://pay.growthmap.test:8443/buy','https://pay.growthmap.test:8443'),'https://pay.growthmap.test:8443/buy');
 assert.equal(validatePurchasePortalUrl('https://xn--bcher-kva.example/buy','https://xn--bcher-kva.example'),'https://xn--bcher-kva.example/buy');
 for(const value of ['http://pay.growthmap.test/buy','https://evil.test/buy','https://user:pass@pay.growthmap.test/buy','https://pay.growthmap.test/buy?x=1','https://pay.growthmap.test/buy#x','https://pay.growthmap.test:443/buy','https://PAY.growthmap.test/buy','https://pay.growthmap.test./buy','https://pay.growthmap.test\\@evil.test/buy','https://pay.growthmap.test/buy?next=https%3A%2F%2Fevil.test','https://pay.growthmap.test/buy#%2f%2fevil.test','\u0000https://pay.growthmap.test/buy'])assert.throws(()=>validatePurchasePortalUrl(value,origin),value);
});
test('purchase target has no renderer context, query, or fragment transport',()=>{
 const target=new URL(purchasePortalTarget(base,origin));assert.equal(target.search,'');assert.equal(target.hash,'');
 assert.equal(purchasePortalTarget.length,2);
});
test('purchase IPC target selection requires exact one-rail arity for x402 and PayPal',()=>{
 const config={purchasePortalUrl:base,purchasePortalOrigin:origin,paypalUrl:'https://paypal.test/exact'},paypal=value=>value===config.paypalUrl;
 assert.equal(purchaseTargetForArgs(['x402'],config,paypal),base);assert.equal(purchaseTargetForArgs(['paypal'],config,paypal),config.paypalUrl);
 for(const args of [[],['x402',null],['x402',{}],['paypal',null],['paypal',{}],['paypal','extra'],['unknown'],[Symbol('rail')],[{}],[1],[true],['x'.repeat(1_000_000)]])assert.throws(()=>purchaseTargetForArgs(args,config,paypal),error=>error.message==='Purchase request has invalid arguments'||error.message==='Purchase request is not configured for this build');
});
