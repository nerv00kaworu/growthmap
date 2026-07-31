export {};
export interface DesktopDatabaseStatus { basename:string; size:number; projects:number; lastBackup:string|null; busy:boolean }
export interface DesktopBackup { id:string; createdAt:string; size:number; projects:number; sha256:string }
export interface ManualPaymentInfo { mode:'manual'; issuer:string; baseNetwork:'eip155:8453'; baseUsdc:string; basePayee:string; earlyLimit:50; earlyPriceMicros:10000000; regularPriceMicros:29000000; paypalUrl:string; supportEmail:string; supportXUrl:string }
declare global {
  interface Window {
    growthmapDesktop?: {
      readonly isDesktop: true;
      readonly agentPortControl: true;
      readonly appInfo: { get():Promise<{productName:string;version:string;creator:string;copyright:string;contactEmail:string;officialXUrl:string;releasePageUrl:string;publisherStatus:'UNSIGNED_BY_OWNER_CHOICE'|'APPROVED';updateMode:'manual'|'automatic'}>; open(target:'releases'|'email'|'x'):Promise<boolean> };
      readonly secrets: { has(id:string):Promise<boolean>; set(id:string,value:string):Promise<boolean>; delete(id:string):Promise<boolean> };
      readonly license: { import():Promise<unknown | null> };
      readonly purchase: { info():Promise<ManualPaymentInfo>; copyBaseAddress():Promise<boolean>; open(rail:'paypal'|'email'|'x'):Promise<boolean> };
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
