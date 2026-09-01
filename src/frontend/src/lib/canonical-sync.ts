import type { CanonicalDelta } from "./api";
import type { GNode, Project } from "./types";
import { findNode, insertChild, patchNode } from "@/stores/tree-utils";

export type CanonicalOwner={projectId:string;branchId:string|null;loadedRevision:number};
export type CanonicalSnapshot={project:Project;root:GNode;selectedId:string|null};
export type CanonicalApplied={project:Project;root:GNode;selected:GNode|null};

const safeInt=(x:unknown):x is number=>Number.isSafeInteger(x)&&Number(x)>0;
function asNode(row:Partial<GNode>):GNode|null{
  if(typeof row.id!=="string"||typeof row.project_id!=="string"||typeof row.title!=="string"||typeof row.node_type!=="string"||typeof row.status!=="string"||typeof row.maturity!=="string"||!safeInt(row.revision))return null;
  // Clone nested values: invalid late items must not mutate the caller's delta.
  const copy=structuredClone(row);
  return {...copy,summary:copy.summary??"",priority:copy.priority??0,confidence:copy.confidence??.5,description:copy.description??"",rules_text:copy.rules_text??"",constraints_text:copy.constraints_text??"",examples_text:copy.examples_text??"",questions_text:copy.questions_text??"",decision_notes:copy.decision_notes??"",workflow_status:copy.workflow_status??"draft",tags:copy.tags??[],file_paths:copy.file_paths??[],created_by:copy.created_by??"",last_edited_by:copy.last_edited_by??"",position_x:copy.position_x??0,position_y:copy.position_y??0,meta:copy.meta??{},content_blocks:copy.content_blocks??[],created_at:copy.created_at??"",updated_at:copy.updated_at??"",children:copy.children??[]} as GNode;
}

/** Strict ordinary-tree delta application. Any unproved topology returns null. */
export function applyCanonicalDelta(owner:CanonicalOwner,snapshot:CanonicalSnapshot,delta:CanonicalDelta):CanonicalApplied|null{
  if(owner.branchId!==null||snapshot.project.id!==owner.projectId||snapshot.project.revision!==owner.loadedRevision)return null;
  if(delta.schema!==1||delta.project_id!==owner.projectId||delta.since_revision!==owner.loadedRevision||!safeInt(delta.current_revision)||delta.current_revision<=owner.loadedRevision||!delta.complete||delta.full_refresh_required||delta.gap||delta.truncated)return null;
  if(!Array.isArray(delta.changes)||delta.changes.some(c=>c.schema!==1||c.kind!=="graph"||c.project_id!==owner.projectId||!safeInt(c.revision)))return null;
  if(delta.branches.length)return null;
  let root=snapshot.root;
  if(delta.edges.some(e=>e.project_id!==owner.projectId||e.relation_type!=="child_of"))return null;
  const edges=new Map<string,(typeof delta.edges)[number]>();
  for(const edge of delta.edges){if(edges.has(edge.to_node_id))return null;edges.set(edge.to_node_id,edge);}
  const incoming=new Map<string,GNode>();
  for(const raw of delta.nodes){const node=asNode(raw);if(!node||node.project_id!==owner.projectId||(node.branch_id??null)!==null)return null;incoming.set(node.id,node);}
  // Existing nodes are scalar patches. New nodes require exactly one authoritative
  // containment edge whose parent exists in the current or incoming snapshot.
  const existingIds=new Set([...incoming.values()].filter(node=>findNode(root,node.id)).map(node=>node.id));
  if(delta.edges.some(edge=>existingIds.has(edge.to_node_id)))return null;
  for(const node of incoming.values())if(findNode(root,node.id))root=patchNode(root,node.id,{...node,children:findNode(root,node.id)?.children??[]});
  for(const node of incoming.values())if(!findNode(root,node.id)){
    const edge=edges.get(node.id);if(!edge)return null;
    const parent=findNode(root,edge.from_node_id);if(!parent||parent.id===node.id||node.id===snapshot.root.id)return null;
    node.meta={...node.meta,edge_id:edge.id,edge_revision:edge.revision};node.is_mainline=edge.is_mainline;
    root=insertChild(root,parent.id,node);
  }
  // Every containment edge must correspond to an attached child and exact parent.
  for(const edge of edges.values()){const parent=findNode(root,edge.from_node_id),child=findNode(root,edge.to_node_id);if(!parent||!child||!(parent.children??[]).some(x=>x.id===child.id))return null;}
  for(const block of delta.content_blocks){const node=findNode(root,block.node_id);if(!node)return null;const blocks=node.content_blocks.filter(b=>b.id!==block.id).concat(block).sort((a,b)=>a.order_index-b.order_index);root=patchNode(root,node.id,{content_blocks:blocks});}
  const project={...snapshot.project,revision:delta.current_revision};
  return {project,root,selected:snapshot.selectedId?findNode(root,snapshot.selectedId):null};
}
