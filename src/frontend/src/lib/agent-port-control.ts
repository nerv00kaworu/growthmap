"use client";
import {useEffect,useState} from "react";
import type {AgentPortReadback} from "./api";
export type AgentPortDesktopMarker={readonly isDesktop?:unknown;readonly agentPortControl?:unknown}|null|undefined;
export function hasAgentPortDesktopControl(marker:AgentPortDesktopMarker):boolean{return marker?.isDesktop===true&&marker?.agentPortControl===true;}
export function useAgentPortDesktopControl():boolean{const[available,setAvailable]=useState(false);useEffect(()=>setAvailable(hasAgentPortDesktopControl(window.growthmapDesktop)),[]);return available;}
export type ReadbackViewModel={targetId:string;revisionLabel:string;stateLabel:string;digestLabel:string;objectiveLabel:string;sections:{label:string;items:unknown[]}[]};
export function readbackViewModel(r:AgentPortReadback,fallbackNodeId:string):ReadbackViewModel{return {targetId:r.target_node_id||fallbackNodeId,revisionLabel:`based on project r${r.based_on_project_revision}`,stateLabel:r.context_stale?`stale · current r${r.current_project_revision}`:`current r${r.current_project_revision}`,digestLabel:r.context_snapshot_digest?`digest ${r.context_snapshot_digest.slice(0,12)}`:"digest unknown",objectiveLabel:r.objective?`objective: ${r.objective}`:"objective: none",sections:[{label:"commits",items:r.commit_refs},{label:"files",items:r.files},{label:"tests",items:r.tests},{label:"decisions",items:r.decisions},{label:"risks",items:r.risks},{label:"todos",items:r.todos},{label:"evidence",items:r.evidence}]};}
