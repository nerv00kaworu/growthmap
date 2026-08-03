"use client";
import {useEffect,useState} from "react";
export type AgentPortDesktopMarker={readonly isDesktop?:unknown;readonly agentPortControl?:unknown}|null|undefined;
export function hasAgentPortDesktopControl(marker:AgentPortDesktopMarker):boolean{return marker?.isDesktop===true&&marker?.agentPortControl===true;}
export function useAgentPortDesktopControl():boolean{const[available,setAvailable]=useState(false);useEffect(()=>setAvailable(hasAgentPortDesktopControl(window.growthmapDesktop)),[]);return available;}
