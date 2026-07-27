export {};
declare global {
  interface Window {
    growthmapDesktop?: {
      readonly isDesktop: true;
      readonly secrets: { has(id:string):Promise<boolean>; set(id:string,value:string):Promise<boolean>; delete(id:string):Promise<boolean> };
      readonly license: { import():Promise<unknown> };
    };
  }
}
