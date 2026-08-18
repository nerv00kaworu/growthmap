import type { ProviderConfig } from "./types";
/** One production predicate shared by every provider-backed control. */
export const providerCredentialPending=(profile:Pick<ProviderConfig,"secret_change_pending">|null|undefined):boolean=>profile?.secret_change_pending===true;
export const providerActionDisabled=(profile:Pick<ProviderConfig,"secret_change_pending">|null|undefined,busy=false):boolean=>busy||!profile||providerCredentialPending(profile);
