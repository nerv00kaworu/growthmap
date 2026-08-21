import React from "react";
import type {DatabaseWorkspaceViewState} from "./database-workspace-state";
import {translate,type Locale,type MessageKey} from "../i18n/catalog";
const keys={"cleanup-pending":"database.cleanupPending","replacement-safe":"database.replacementSafe","replacement-unknown":"database.replacementUnknown",failure:"database.operationFailure"} as const satisfies Record<string,MessageKey>;
export type DatabaseMessageKey=keyof typeof keys;
export function databaseWorkspaceMessage(key:DatabaseMessageKey,locale:Locale){return translate(locale,keys[key])}
export function DatabaseCleanupBanner({view,locale}:{view:DatabaseWorkspaceViewState;locale:Locale}){return view.cleanupBanner?<div data-testid="database-cleanup-pending" className="rounded border border-amber-700">{databaseWorkspaceMessage("cleanup-pending",locale)}</div>:null}
export function DatabaseOperationMessage({kind,locale}:{kind:Extract<DatabaseMessageKey,"replacement-safe"|"replacement-unknown"|"failure">;locale:Locale}){return <div data-testid="database-operation-fixed">{databaseWorkspaceMessage(kind,locale)}</div>}
