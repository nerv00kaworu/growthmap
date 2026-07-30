import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import {ReadbackCard} from "./AgentPortPanel";
import type {AgentPortReadback} from "../lib/api";
const base:AgentPortReadback={id:"r",target_node_id:"target",summary:"done",based_on_project_revision:1,context_snapshot_digest:"a".repeat(64),objective:"",current_project_revision:1,context_stale:false,commit_refs:[],files:[],tests:[],decisions:[],risks:[],todos:[],evidence:[],created_at:"now"};
function findButton(node:unknown):React.ReactElement<{onClick:()=>void}>{if(React.isValidElement(node)){if(node.type==="button")return node as React.ReactElement<{onClick:()=>void}>;const children=(node.props as {children?:React.ReactNode}).children;for(const child of React.Children.toArray(children)){try{return findButton(child)}catch{}}}throw new Error("button not found")}
test("readback target button invokes selection for target and root fallback",()=>{for(const [target,expected] of [["target","target"],[null,"root"]] as const){let selected="";const tree=ReadbackCard({readback:{...base,target_node_id:target},fallbackNodeId:"root",onSelectNode:id=>{selected=id}});findButton(tree).props.onClick();assert.equal(selected,expected)}});
