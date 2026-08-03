export {};
export interface DesktopDatabaseStatus { basename:string; size:number; projects:number; lastBackup:string|null; busy:boolean }
export interface CommercialPublicConfig { licenseIssuer:string; supportEmail:string; supportUrl:string; baseNetwork:string; basePayee:string; paypalUrl:string }
export interface DesktopBackup { id:string; createdAt:string; size:number; projects:number; sha256:string }
declare global {
  interface Window {
    growthmapDesktop?: {
      readonly isDesktop: true;
      readonly agentPortControl: true;
      readonly secrets: { has(id:string):Promise<boolean>; set(id:string,value:string):Promise<boolean>; delete(id:string):Promise<boolean> };
      readonly license: { import():Promise<unknown | null> };
      readonly purchase: { open(rail:'x402'|'paypal'):Promise<boolean>; publicConfig():Promise<CommercialPublicConfig>; copyBasePayee():Promise<boolean> };
      readonly support: { open():Promise<boolean> };
      readonly entitlement: { onChanged(callback:()=>void):()=>void };
      readonly updates: { check():Promise<unknown> };
      readonly database: {
        status():Promise<DesktopDatabaseStatus>;
        import():Promise<{ok:true}|null>;
        backup():Promise<{ok:true;projects:number}>;
        listBackups():Promise<DesktopBackup[]>;
        restore(id:string):Promise<{ok:true}>;
        revealFolder():Promise<unknown>;
      };
    };
  }
}
