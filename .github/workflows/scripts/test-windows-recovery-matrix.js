'use strict';

const assert = require('node:assert/strict');
const cp = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { createDatabaseManager } = require('../../../desktop/database-manager');

const root = process.env.GM_BOUNDARY_ROOT;
const sidecar = process.env.GM_BOUNDARY_SIDECAR;
const fixture = process.env.GM_BOUNDARY_FIXTURE;
assert(root && sidecar && fixture, 'boundary harness environment is incomplete');

function maintenance(flag, file, destination) {
  const env = { ...process.env, GROWTHMAP_DESKTOP_MODE: '1' };
  if (destination) env.GROWTHMAP_MAINTENANCE_DESTINATION = destination;
  const result = cp.spawnSync(sidecar, [flag, file], { env, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, `${flag} failed for ${file}: ${result.stderr}`);
  return JSON.parse(result.stdout);
}

function scenario(name, live = true) {
  const dir = path.join(root, `recovery-${name}`);
  fs.mkdirSync(dir);
  const databasePath = path.join(dir, 'growthmap.db');
  if (live) fs.copyFileSync(fixture, databasePath);
  const manager = createDatabaseManager({
    userData: dir,
    databasePath,
    executable: sidecar,
    stopSidecar: async () => {},
    startSidecar: async () => {},
    reload: async () => {},
    showOpenDialog: async () => ({ canceled: true }),
    reveal: async () => {},
  });
  return { dir, databasePath, manager };
}

function residue(dir, kind, id) {
  const target = path.join(dir, `growthmap.db.gm-${kind}-${id}`);
  fs.copyFileSync(fixture, target);
  maintenance('--validate-db', target);
  return target;
}

(async () => {
  // Valid live wins. Both old/new residues are preserved as quarantined evidence.
  let item = scenario('valid-live-old-new');
  const liveBefore = maintenance('--validate-db', item.databasePath).sha256;
  residue(item.dir, 'old', '11111111-1111-4111-8111-111111111111');
  residue(item.dir, 'new', '22222222-2222-4222-8222-222222222222');
  let result = await item.manager.recoverStartup();
  assert.deepEqual(result, { recovered: false, residuesQuarantined: 2 });
  assert.equal(maintenance('--validate-db', item.databasePath).sha256, liveBefore);
  assert.equal(fs.readdirSync(item.dir).filter((name) => name.includes('.quarantine-')).length, 2);
  console.log('PASS valid live + old/new: live preserved, residues quarantined');

  // Corrupt live plus exactly one valid old recovers, retaining the corrupt file.
  item = scenario('corrupt-live-one-valid-old');
  fs.writeFileSync(item.databasePath, 'deliberately corrupt');
  residue(item.dir, 'old', '33333333-3333-4333-8333-333333333333');
  result = await item.manager.recoverStartup();
  assert.deepEqual(result, { recovered: true, evidenceRetained: true });
  assert.equal(maintenance('--validate-db', item.databasePath).sha256, maintenance('--validate-db', fixture).sha256);
  assert.equal(fs.readdirSync(item.dir).filter((name) => name.includes('.gm-corrupt-')).length, 1);
  console.log('PASS corrupt live + one valid old: recovered with corrupt evidence retained');

  // Missing live plus multiple valid olds is ambiguous and must not mutate evidence.
  item = scenario('missing-live-ambiguous-olds', false);
  const oldA = residue(item.dir, 'old', '44444444-4444-4444-8444-444444444444');
  const oldB = residue(item.dir, 'old', '55555555-5555-4555-8555-555555555555');
  const before = [oldA, oldB].map((file) => maintenance('--validate-db', file).sha256);
  await assert.rejects(item.manager.recoverStartup(), (error) => error.recoveryRequired === true);
  assert.equal(fs.existsSync(item.databasePath), false);
  assert.deepEqual([oldA, oldB].map((file) => maintenance('--validate-db', file).sha256), before);
  console.log('PASS missing live + ambiguous olds: failed closed without mutation');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
