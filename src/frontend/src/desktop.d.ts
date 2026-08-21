export {};
export type DesktopDatabaseCleanup = { pending:true; stage:"committed-old-cleanup" };
export type DesktopDatabaseReplacement = { ok:true; cleanup:null|DesktopDatabaseCleanup };
export interface DesktopDatabaseStatus { basename:string; directory:string; databasePath:string; size:number; projects:number; sha256:string; lastBackup:string|null; busy:boolean; cleanupPending:boolean }
export interface CommercialPublicConfig { licenseIssuer:string; supportEmail:string; supportUrl:string }
export interface DesktopBackup { id:string; createdAt:string; size:number; projects:number; sha256:string }
declare global {
  interface Window {
    growthmapDesktop?: {
      readonly isDesktop: true;
      readonly agentPortControl: true;
      readonly agentPort:{list(p:string):Promise<Record<string,unknown>[]>;create(d:Record<string,unknown>):Promise<Record<string,unknown>>;revoke(id:string):Promise<unknown>;activity(p:string,t?:string):Promise<import("./lib/api").AgentPortActivity>;review(id:string,d:"approve"|"reject",n?:string):Promise<unknown>};
      readonly agentAccess:{status():Promise<Record<string,unknown>>;enable(o:Record<string,unknown>):Promise<Record<string,unknown>>;disable():Promise<Record<string,unknown>>;copy():Promise<boolean>;download():Promise<{saved:boolean}>;test():Promise<{ok:boolean;status:string}>;regenerate():Promise<Record<string,unknown>>};
      readonly secrets: { has(id:string):Promise<boolean>; set(id:string,value:string):Promise<boolean>; delete(id:string):Promise<boolean>; recover(id:string,revision:number,operation:"set"|"delete",value?:string):Promise<boolean> };
      readonly license: { import():Promise<unknown | null>; activate(key:string):Promise<unknown> };
      readonly revocation: { import():Promise<unknown | null> };
      readonly purchase: { open():Promise<boolean>; publicConfig():Promise<CommercialPublicConfig> };
      readonly support: { open():Promise<boolean> };
      readonly entitlement: { onChanged(callback:()=>void):()=>void };
      readonly updates: { check():Promise<unknown> };
      readonly database: {
        status():Promise<DesktopDatabaseStatus>;
        chooseWorkspace():Promise<{ok:true;restarting:true;directory:string}|null>;
        import():Promise<DesktopDatabaseReplacement|null>;
        backup():Promise<{ok:true;projects:number}>;
        listBackups():Promise<DesktopBackup[]>;
        restore(id:string):Promise<DesktopDatabaseReplacement>;
        revealFolder():Promise<unknown>;
      };
    };
  }
}
