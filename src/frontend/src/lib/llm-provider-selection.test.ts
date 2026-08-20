import test from "node:test";import assert from "node:assert/strict";import {resolveAuthoritativeLLMConfig} from "./llm-provider";
const local=new Map<string,string>();Object.assign(globalThis,{localStorage:{getItem:(k:string)=>local.get(k)??null,setItem:(k:string,v:string)=>local.set(k,v)}});
const p=(id:string,is_default=false,enabled=true)=>({id,name:id,provider_type:"mock",model_name:id,revision:1,enabled,is_default});
test("new origin restores backend default and multi-profile absence fails closed",()=>{local.clear();assert.equal(resolveAuthoritativeLLMConfig([p("a"),p("b",true)])?.providerId,"b");local.clear();assert.equal(resolveAuthoritativeLLMConfig([p("a"),p("b")]),null)});
test("disabled default is ignored",()=>{local.clear();assert.equal(resolveAuthoritativeLLMConfig([p("a",true,false)]),null)});
