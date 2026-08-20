import assert from "node:assert/strict";
import test from "node:test";
import { initialSettingsSaveState, reduceSettingsSave, type SettingsSaveState } from "./settings-save-state";

test("metadata failure identifies the first durable stage", () => {
  const state=reduceSettingsSave(reduceSettingsSave(initialSettingsSaveState,{type:"START"}),{type:"METADATA_FAIL"});
  assert.equal(state.phase,"metadata_failed"); assert.equal(state.metadataSaved,false);
});
test("secret partial failure preserves durable metadata and recovery state", () => {
  let state=reduceSettingsSave(initialSettingsSaveState,{type:"START"});
  state=reduceSettingsSave(state,{type:"METADATA_OK",providerId:"p"});
  state=reduceSettingsSave(state,{type:"SECRET_FAIL"});
  assert.deepEqual([state.phase,state.metadataSaved,state.secretSaved,state.providerId],["secret_failed",true,false,"p"]);
});
test("PUT failure/readback failure remains retry only when PUT itself was retryable", () => {
  let state: SettingsSaveState={...initialSettingsSaveState,phase:"refresh",providerId:"p",metadataSaved:true,secretSaved:true};
  state=reduceSettingsSave(state,{type:"REFRESH_OK",selectionRevision:8});
  state=reduceSettingsSave(state,{type:"SELECTION_RETRY",selectionRevision:9});
  assert.deepEqual([state.phase,state.selectionRevision],["selection_retry",9]);
});
test("commit success then readback failure remains committed and cannot offer mutation retry", () => {
  let state: SettingsSaveState={phase:"selection",providerId:"p",metadataSaved:true,secretSaved:true,selectionRevision:9};
  state=reduceSettingsSave(state,{type:"SELECTION_COMMITTED",selectionRevision:10});
  state=reduceSettingsSave(state,{type:"READBACK_FAIL"});
  state=reduceSettingsSave(state,{type:"SELECTION_RETRY",selectionRevision:11});
  assert.deepEqual([state.phase,state.selectionRevision],["selection_committed",10]);
});
test("retry performs one committed transition then readback only", () => {
  let puts=0;
  let state: SettingsSaveState={phase:"selection_retry",providerId:"p",metadataSaved:true,secretSaved:true,selectionRevision:9};
  puts++; state=reduceSettingsSave(state,{type:"SELECTION_COMMITTED",selectionRevision:10});
  state=reduceSettingsSave(state,{type:"READBACK_OK"});
  assert.deepEqual([state.phase,puts],["saved",1]);
});
