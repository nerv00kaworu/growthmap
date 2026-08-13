export const site={name:'GrowthMap',support:'nerv00kaworu@gmail.com',x:'nerv00kaworu',canonicalBase:process.env.NEXT_PUBLIC_CANONICAL_BASE?.replace(/\/$/,'')};
/** Primary product navigation only. Legal/support routes intentionally remain contextual. */
export const primaryRoutes=['','/features','/agents','/security','/download','/license','/buy'] as const;
// Compatibility exports for non-localized legacy components; these are not primary navigation.
export const nav=[['功能','/features'],['AI 協作與治理','/agents'],['實作讀回','/readback']] as const;
export const faq=[['GrowthMap 是雲端專案管理工具嗎？','不是。GrowthMap 是 Windows 本機優先的專案工作區；公開網站不會接收專案資料。'],['目前可以購買或下載嗎？','Windows x64 下載與 Whop Personal 購買已開放；請只從 growthmap.work 取得安裝程式。']] as const;
