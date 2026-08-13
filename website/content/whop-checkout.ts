export const whopProducts={
  early:'https://whop.com/growthmap/growthmap-early/',
  standard:'https://whop.com/growthmap/growthmap/'
} as const;

export type WhopProduct=keyof typeof whopProducts;
