export type ProjectOwner={project:string;ticket:number};
export type ProjectScoped<T>={project:string;value:T};
export const owns=(owner:ProjectOwner|null,project:string,ticket:number)=>owner?.project===project&&owner.ticket===ticket;
export const visibleFor=<T>(scoped:ProjectScoped<T>|null,project:string,fallback:T)=>scoped?.project===project?scoped.value:fallback;
export const releaseOwned=(owner:ProjectOwner|null,settling:ProjectOwner)=>owns(owner,settling.project,settling.ticket)?null:owner;
