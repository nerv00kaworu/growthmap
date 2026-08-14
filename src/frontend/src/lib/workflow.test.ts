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

test("non-conflict errors do not refresh", async () => {
  let refreshes = 0;
  await assert.rejects(() => runMutationWithConflict(
    async () => { throw new ApiError(422, "VALIDATION", "bad"); },
    async () => { refreshes += 1; },
  ));
  assert.equal(refreshes, 0);
});
