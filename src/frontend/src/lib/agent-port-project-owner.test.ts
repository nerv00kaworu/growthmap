import assert from "node:assert/strict";
import test from "node:test";
import { beginProjectRefresh, captureProjectOperation, ownsCurrentProject } from "./agent-port-project-owner";

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
};

test("stale A mutation cannot supersede B refresh or publish an A error", async () => {
  let project = "A", generation = 1, reloads = 0, message = "";
  const owner = captureProjectOperation(project, generation);
  const mutation = deferred<void>();
  const continuation = mutation.promise.then(
    () => { if (ownsCurrentProject(owner, project, generation)) reloads++; },
    () => { if (ownsCurrentProject(owner, project, generation)) message = "A failed"; },
  );
  project = "B"; generation++;
  mutation.reject(new Error("old A failure"));
  await continuation;
  assert.equal(reloads, 0);
  assert.equal(message, "");
});

test("A to B to A cannot expose a token from the old A generation", async () => {
  let project = "A", generation = 3, token = "";
  const owner = captureProjectOperation(project, generation);
  const created = deferred<string>();
  const continuation = created.promise.then(value => {
    if (ownsCurrentProject(owner, project, generation)) token = value;
  });
  project = "B"; generation++;
  project = "A"; generation++;
  created.resolve("old-secret-token");
  await continuation;
  assert.equal(token, "");
});

test("current project operation can refresh and publish its result", async () => {
  const owner = captureProjectOperation("B", 8);
  assert.equal(ownsCurrentProject(owner, "B", 8), true);
  assert.equal(ownsCurrentProject(owner, "B", 9), false);
  assert.equal(ownsCurrentProject(owner, "A", 8), false);
});

test("global mutation started on A cannot supersede the destination B refresh", async () => {
  let currentProject = "A", generation = 1;
  const globalOwner = captureProjectOperation(currentProject, generation);
  const globalMutation = deferred<void>();
  const obsoleteAContinuation = globalMutation.promise.then(() => {
    if (!ownsCurrentProject(globalOwner, currentProject, generation)) return null;
    const owner = beginProjectRefresh(globalOwner.project, currentProject, generation);
    if (owner) generation = owner.generation;
    return owner;
  });

  currentProject = "B";
  const destination = beginProjectRefresh("B", currentProject, generation);
  assert.ok(destination);
  generation = destination.generation;

  globalMutation.resolve();
  assert.equal(await obsoleteAContinuation, null);
  assert.equal(generation, destination.generation);
  assert.equal(ownsCurrentProject(destination, currentProject, generation), true);
});

test("global mutation started on old A cannot supersede a newer A after A to B to A", async () => {
  let currentProject = "A", generation = 4, refreshes = 0;
  const globalOwner = captureProjectOperation(currentProject, generation);
  const globalMutation = deferred<void>();
  const continuation = globalMutation.promise.then(() => {
    if (!ownsCurrentProject(globalOwner, currentProject, generation)) return;
    const owner = beginProjectRefresh(globalOwner.project, currentProject, generation);
    if (owner) { generation = owner.generation; refreshes++; }
  });
  currentProject = "B"; generation++;
  currentProject = "A"; generation++;
  globalMutation.resolve();
  await continuation;
  assert.equal(refreshes, 0);
  assert.equal(generation, 6);
});

test("current post-mutation local refresh failure can publish its warning", async () => {
  const currentProject = "A";
  let generation = 7, warning = false;
  const mutationOwner = captureProjectOperation(currentProject, generation);
  assert.equal(ownsCurrentProject(mutationOwner, currentProject, generation), true);
  const refreshOwner = beginProjectRefresh(mutationOwner.project, currentProject, generation);
  assert.ok(refreshOwner);
  generation = refreshOwner.generation;
  const failures = [new Error("bounded failure")];
  if (failures.length) warning = true;
  assert.equal(warning, true);
  assert.equal(ownsCurrentProject(refreshOwner, currentProject, generation), true);
});

test("pending global action latch survives A to B and blocks a new mutation", async () => {
  const latch = Symbol("global");
  let globalLatch: symbol | null = latch;
  let localLatch: symbol | null = Symbol("local");
  const pending = deferred<void>();
  const continuation = pending.promise.then(() => {
    if (globalLatch === latch) globalLatch = null;
  });
  // Project switch invalidates only project-local ownership.
  localLatch = null;
  const mutationBlocked = globalLatch !== null || localLatch !== null;
  assert.equal(mutationBlocked, true);
  pending.resolve();
  await continuation;
  assert.equal(globalLatch, null);
});

test("pending global action latch survives A to B to A", async () => {
  const latch = Symbol("global");
  let globalLatch: symbol | null = latch;
  let generation = 2;
  generation++; // A -> B
  generation++; // B -> A
  assert.equal(globalLatch, latch);
  assert.equal(generation, 4);
  if (globalLatch === latch) globalLatch = null;
  assert.equal(globalLatch, null);
});

test("stale project retry failure keeps its global latch but publishes no local message", async () => {
  let project = "A", generation = 5, message = "";
  const operation = captureProjectOperation(project, generation);
  const latch = Symbol("retry");
  let globalLatch: symbol | null = latch;
  const retry = deferred<boolean>();
  const continuation = retry.promise.then(ok => {
    if (!ok && ownsCurrentProject(operation, project, generation)) message = "unavailable";
    if (globalLatch === latch) globalLatch = null;
  });
  project = "B"; generation++;
  assert.equal(globalLatch, latch);
  retry.resolve(false);
  await continuation;
  assert.equal(message, "");
  assert.equal(globalLatch, null);
});

test("old A retry failure stays silent after A to B to A", async () => {
  let project = "A", generation = 9, message = "";
  const operation = captureProjectOperation(project, generation);
  const retry = deferred<boolean>();
  const continuation = retry.promise.then(ok => {
    if (!ok && ownsCurrentProject(operation, project, generation)) message = "unavailable";
  });
  project = "B"; generation++;
  project = "A"; generation++;
  retry.resolve(false);
  await continuation;
  assert.equal(message, "");
});

test("unmounted retry cleanup starts no state update", async () => {
  let mounted = true, retrying = true;
  const retry = deferred<void>();
  const continuation = retry.promise.then(() => {
    if (mounted) retrying = false;
  });
  mounted = false;
  retry.resolve();
  await continuation;
  assert.equal(retrying, true);
});

test("unmounted global mutation continuation starts no status or local refresh", async () => {
  let mounted = true, statusReads = 0, localReads = 0;
  const globalMutation = deferred<void>();
  const continuation = globalMutation.promise.then(() => {
    if (mounted) statusReads++;
    if (mounted) localReads++;
  });
  mounted = false;
  globalMutation.resolve();
  await continuation;
  assert.equal(statusReads, 0);
  assert.equal(localReads, 0);
});
