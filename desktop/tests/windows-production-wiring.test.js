'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createWindowsProductionWiring,createOrderlyShutdown}=require('../windows-production-wiring');

test('win32 production wiring injects one shared broker into native opener and replacement owner',async()=>{
 const broker={start:async()=>{},close:async()=>{}};let creates=0,openBroker,ownerBroker;
 const wiring=createWindowsProductionWiring({platform:'win32',createBroker:()=>{creates++;return broker},createNativeOpen:options=>{openBroker=options.broker;return async()=>{}},createReplacementOwner:options=>{ownerBroker=options.broker;return {}}});
 assert.equal(creates,1);assert.equal(wiring.broker,broker);assert.equal(openBroker,broker);assert.equal(ownerBroker,broker);await wiring.assertAvailable();
});

test('win32 missing broker helper fails closed before mutation callbacks',async()=>{
 const expected=Object.assign(Error('unavailable'),{code:'WINDOWS_NATIVE_BROKER_UNAVAILABLE',stage:'helper'});let opened=0,prepared=0;
 const wiring=createWindowsProductionWiring({platform:'win32',createBroker:()=>({start:async()=>{throw expected},close:async()=>{}}),createNativeOpen:({broker})=>async()=>{opened++;return broker},createReplacementOwner:({broker})=>({prepare:async()=>{prepared++;return broker}})});
 await assert.rejects(wiring.assertAvailable(),error=>error===expected);assert.equal(opened,0);assert.equal(prepared,0);
});

test('non-Windows production wiring creates no broker or native dependencies',async()=>{
 let called=0;const wiring=createWindowsProductionWiring({platform:'linux',createBroker:()=>{called++;throw Error('must not run')},createNativeOpen:()=>{called++},createReplacementOwner:()=>{called++}});
 assert.deepEqual({broker:wiring.broker,nativeOpen:wiring.nativeOpen,owner:wiring.windowsReplacementOwner},{broker:null,nativeOpen:null,owner:null});assert.equal(called,0);await wiring.assertAvailable();
});

test('orderly shutdown awaits DB idle, sidecar cleanup, broker tree close once across triggers and errors',async()=>{
 const order=[];let brokerCloses=0,quits=0;let releaseIdle;const idle=new Promise(resolve=>releaseIdle=resolve);const manager={busy:true,async awaitIdle(){order.push('idle-wait');await idle;order.push('idle')}};
 const lifecycle={beginShutdown(){order.push('begin')},async shutdown(closeWindow){order.push('lifecycle');closeWindow();throw Error('sidecar cleanup failed')}};
 const broker={async close(){brokerCloses++;order.push('broker-close')}};const window={isDestroyed:()=>false,destroy:()=>order.push('window-close')};
 const shutdown=createOrderlyShutdown({lifecycle,getDatabaseManager:()=>manager,getMainWindow:()=>window,broker,quit:()=>{quits++;order.push('quit')}});
 const first=shutdown(),second=shutdown();assert.equal(first,second);assert.deepEqual(order,['begin','idle-wait']);releaseIdle();await assert.rejects(first,/sidecar cleanup failed/);assert.equal(brokerCloses,1);assert.equal(quits,1);assert.deepEqual(order,['begin','idle-wait','idle','lifecycle','window-close','broker-close','quit']);await assert.rejects(shutdown(),/sidecar cleanup failed/);assert.equal(brokerCloses,1);assert.equal(quits,1);
});

test('orderly shutdown still awaits broker close rejection and quits exactly once',async()=>{
 let closes=0,quits=0;const shutdown=createOrderlyShutdown({lifecycle:{beginShutdown(){},async shutdown(){}},getDatabaseManager:()=>null,getMainWindow:()=>null,broker:{async close(){closes++;throw Error('broker close failed')}},quit:()=>{quits++}});
 await assert.rejects(Promise.all([shutdown(),shutdown()]),/broker close failed/);assert.equal(closes,1);assert.equal(quits,1);
});
