'use strict';
/** Credential reconciliation is a hard startup barrier. */
async function runCredentialStartup({store,hydrate=()=>store.hydrate(),enable}){
 await store.reconcile();
 await hydrate();
 await enable();
}
module.exports={runCredentialStartup};
