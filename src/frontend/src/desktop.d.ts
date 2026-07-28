export {};
export interface DesktopDatabaseStatus { basename:string; size:number; projects:number; lastBackup:string|null; busy:boolean }
export interface DesktopBackup { id:string; createdAt:string; size:number; projects:number; sha256:string }
declare global {
  interface Window {
    growthmapDesktop?: {
      readonly isDesktop: true;
      readonly secrets: { has(id:string):Promise<boolean>; set(id:string,value:string):Promise<boolean>; delete(id:string):Promise<boolean> };
      readonly license: { import():Promise<unknown>; checkout():Promise<boolean> };
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
