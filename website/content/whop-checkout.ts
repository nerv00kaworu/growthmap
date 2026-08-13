export type WhopSalesPhase='early'|'standard';

const checkoutByPhase:Record<WhopSalesPhase,string>={
  early:'https://whop.com/growthmap/growthmap-early/',
  standard:'https://whop.com/growthmap/growthmap/'
};

/**
 * The public product URLs are fixed and reviewed.  Only an explicit build-time
 * sales phase exposes one of them; absent or unknown configuration fails closed.
 */
export function parseWhopSalesPhase(value:string|undefined):WhopSalesPhase|undefined{
  return value==='early'||value==='standard'?value:undefined;
}

export function checkoutForPhase(value:string|undefined):string|undefined{
  const phase=parseWhopSalesPhase(value);
  return phase?checkoutByPhase[phase]:undefined;
}

export const whopSalesPhase=parseWhopSalesPhase(process.env.NEXT_PUBLIC_WHOP_SALES_PHASE);
export const whopCheckoutUrl=checkoutForPhase(process.env.NEXT_PUBLIC_WHOP_SALES_PHASE);
