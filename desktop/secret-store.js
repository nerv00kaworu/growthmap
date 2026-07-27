'use strict';
const fs = require('node:fs');
const path = require('node:path');

function createSecretStore({ directory, encrypt, decrypt, putRemote, deleteRemote, warn = () => {} }) {
  const validId = id => { if (!/^[A-Za-z0-9-]{1,80}$/.test(id)) throw new Error('Invalid provider id'); return id; };
  const file = id => path.join(directory, `${validId(id)}.bin`);
  const quarantine = (target, reason) => {
    const moved = `${target}.quarantine-${Date.now()}`;
    try { fs.renameSync(target, moved); } catch { try { fs.unlinkSync(target); } catch {} }
    warn(`A stored provider key was quarantined (${reason}). Re-enter it in Settings.`);
  };
  const oldValue = target => fs.existsSync(target) ? decrypt(fs.readFileSync(target)) : null;
  return {
    has(id) { return fs.existsSync(file(id)); },
    async set(id, value) {
      if (typeof value !== 'string' || !value || value.includes('\0')) throw new Error('API key is required');
      const target = file(id); fs.mkdirSync(directory, { recursive: true });
      let previous = null; try { previous = oldValue(target); } catch { quarantine(target, 'unreadable'); }
      const temp = `${target}.tmp-${process.pid}-${Date.now()}`;
      try {
        fs.writeFileSync(temp, encrypt(value), { mode: 0o600, flag: 'wx' });
        await putRemote(id, value);
        try { fs.renameSync(temp, target); }
        catch (error) { if (previous !== null) await putRemote(id, previous); else await deleteRemote(id); throw error; }
        return true;
      } catch (error) { try { fs.unlinkSync(temp); } catch {} throw new Error('API key could not be stored securely'); }
    },
    async delete(id) {
      const target = file(id); if (!fs.existsSync(target)) { await deleteRemote(id); return true; }
      let previous; try { previous = oldValue(target); } catch { quarantine(target, 'unreadable'); await deleteRemote(id); return true; }
      await deleteRemote(id);
      try { fs.unlinkSync(target); }
      catch { try { await putRemote(id, previous); } catch {} throw new Error('API key could not be removed securely'); }
      return true;
    },
    async hydrate() {
      if (!fs.existsSync(directory)) return;
      for (const name of fs.readdirSync(directory)) {
        if (!name.endsWith('.bin')) continue;
        const target = path.join(directory, name), id = name.slice(0, -4);
        let value; try { value = decrypt(fs.readFileSync(target)); } catch { quarantine(target, 'corrupt'); continue; }
        try { await putRemote(id, value); }
        catch (error) { if (error && error.statusCode === 404) quarantine(target, 'stale provider'); else warn('One stored provider key could not be loaded. Re-enter it in Settings.'); }
      }
    }
  };
}
module.exports = { createSecretStore };
