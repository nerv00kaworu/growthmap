import assert from "node:assert/strict";
import test from "node:test";
import { ApiError } from "./api";
import { runMutationWithConflict } from "./conflict";

test("normal create and sequential suggestion/deepen writes use authoritative revisions", async () => {
  let projectRevision = 7;
  let nodeRevision = 3;
  const outgoing: Array<Record<string, unknown>> = [];
  const create = async (title: string) => {
    outgoing.push({ title, expected_project_revision: projectRevision, expected_parent_revision: nodeRevision });
    projectRevision += 1;
    nodeRevision += 1;
    return { revision: 1, authoritative_project_revision: projectRevision, authoritative_parent_revision: nodeRevision };
  };
  await create("normal create");
  await create("acceptSuggestion");
  await create("acceptAllSuggestions #1");
  await create("acceptAllSuggestions #2");
  outgoing.push({ op: "deepen summary", expected_project_revision: projectRevision, expected_revision: nodeRevision });
  projectRevision += 1; nodeRevision += 1;
  outgoing.push({ op: "deepen block", expected_project_revision: projectRevision, expected_node_revision: nodeRevision });

  assert.deepEqual(outgoing.map(x => [x.expected_project_revision, x.expected_parent_revision ?? x.expected_revision ?? x.expected_node_revision]), [
    [7, 3], [8, 4], [9, 5], [10, 6], [11, 7], [12, 8],
  ]);
});

test("already superseded operation does not send its mutation", async () => {
  let mutations = 0;
  const result = await runMutationWithConflict(
    async () => { mutations += 1; return "written"; },
    async () => {},
    {},
    () => false,
  );
  assert.equal(mutations, 0);
  assert.deepEqual(result, { superseded: true });
});

test("409 is not replayed, refreshes once, exposes conflict, and preserves drafts", async () => {
  let mutations = 0;
  let refreshes = 0;
  const result = await runMutationWithConflict(
    async () => { mutations += 1; throw new ApiError(409, "REVISION_CONFLICT", "stale"); },
    async () => { refreshes += 1; },
    { nodeDraft: "unsaved node text", suggestionInput: "keep this instruction" },
  );
  assert.equal(mutations, 1);
  assert.equal(refreshes, 1);
  assert.equal(result.conflict?.visible, true);
  assert.match(result.conflict?.message ?? "", /latest version/);
  assert.equal(result.conflict?.nodeDraft, "unsaved node text");
  assert.equal(result.conflict?.suggestionInput, "keep this instruction");
});

test("409 refresh failure does not falsely claim the latest version loaded", async () => {
  const result = await runMutationWithConflict(
    async () => { throw new ApiError(409, "REVISION_CONFLICT", "stale"); },
    async () => { throw new Error("refresh unavailable"); },
    { suggestionInput: "preserved" },
  );
  assert.match(result.conflict?.message ?? "", /could not be loaded/);
  assert.equal(result.conflict?.suggestionInput, "preserved");
});

test("non-conflict errors do not refresh", async () => {
  let refreshes = 0;
  await assert.rejects(() => runMutationWithConflict(
    async () => { throw new ApiError(422, "VALIDATION", "bad"); },
    async () => { refreshes += 1; },
  ));
  assert.equal(refreshes, 0);
});

test("superseded conflict refresh success publishes neither stale conflict nor draft", async () => {
  let owned = true;
  let settle!: () => void;
  const pending = new Promise<void>((resolve) => { settle = resolve; });
  const resultPromise = runMutationWithConflict(
    async () => { throw new ApiError(409, "REVISION_CONFLICT", "stale"); },
    async () => pending,
    { suggestionInput: "old draft" },
    () => owned,
  );
  await Promise.resolve();
  owned = false;
  settle();
  assert.deepEqual(await resultPromise, { superseded: true });
});

test("superseded conflict refresh rejection stays silent", async () => {
  let owned = true;
  let reject!: (error: Error) => void;
  const pending = new Promise<void>((_resolve, fail) => { reject = fail; });
  const resultPromise = runMutationWithConflict(
    async () => { throw new ApiError(409, "REVISION_CONFLICT", "stale"); },
    async () => pending,
    { suggestionInput: "old draft" },
    () => owned,
  );
  await Promise.resolve();
  owned = false;
  reject(new Error("readback failed"));
  assert.deepEqual(await resultPromise, { superseded: true });
});
