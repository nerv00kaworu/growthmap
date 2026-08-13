import type {Locale} from './i18n';

type LicenseContent={
  eyebrow:string;title:string;lead:string;plansLabel:string;
  early:string;earlyBadge:string;earlyPrice:string;earlyBody:string;buyEarly:string;
  standard:string;standardBadge:string;standardPrice:string;standardBody:string;buyStandard:string;
  includedTitle:string;included:string[];flowTitle:string;flow:string[];download:string;
};

export const licenseContent:Record<Locale,LicenseContent>={
  'zh-TW':{
    eyebrow:'PERSONAL v1 授權',title:'一次購買，永久使用 GrowthMap Personal v1。',
    lead:'解鎖不限同時啟用的專案，最多可在 2 台個人裝置使用。兩種價格提供相同的 Personal v1 授權內容。',
    plansLabel:'選擇 Personal v1 方案',
    early:'Early',earlyBadge:'全球前 50 筆',earlyPrice:'US$10',earlyBody:'一次性付款。依付款確認並成功發證的順序分配；開啟結帳不會保留名額。',buyEarly:'購買 Early — US$10',
    standard:'Standard',standardBadge:'第 51 筆起',standardPrice:'US$29',standardBody:'一次性付款。Early 名額用完後使用此正式價格，授權內容完全相同。',buyStandard:'購買 Standard — US$29',
    includedTitle:'Personal v1 包含',included:['Personal v1 永久授權','不限同時啟用的專案數量','最多 2 台個人裝置','Personal v1 後續更新'],
    flowTitle:'購買與啟用',flow:['在 Whop 完成 Early 或 Standard 付款。','進入 Whop 內的 GrowthMap License Experience。','複製只屬於你的 GM1 啟用碼。','在 Windows 桌面版輸入完整啟用碼。'],
    download:'先下載 Windows 版本'
  },
  'zh-CN':{
    eyebrow:'PERSONAL v1 授权',title:'一次购买，永久使用 GrowthMap Personal v1。',
    lead:'解锁不限同时启用的项目，最多可在 2 台个人设备使用。两种价格提供相同的 Personal v1 授权内容。',
    plansLabel:'选择 Personal v1 方案',
    early:'Early',earlyBadge:'全球前 50 笔',earlyPrice:'US$10',earlyBody:'一次性付款。按付款确认并成功发证的顺序分配；打开结账不会保留名额。',buyEarly:'购买 Early — US$10',
    standard:'Standard',standardBadge:'第 51 笔起',standardPrice:'US$29',standardBody:'一次性付款。Early 名额用完后使用此正式价格，授权内容完全相同。',buyStandard:'购买 Standard — US$29',
    includedTitle:'Personal v1 包含',included:['Personal v1 永久授权','不限同时启用的项目数量','最多 2 台个人设备','Personal v1 后续更新'],
    flowTitle:'购买与激活',flow:['在 Whop 完成 Early 或 Standard 付款。','进入 Whop 内的 GrowthMap License Experience。','复制只属于你的 GM1 激活码。','在 Windows 桌面版输入完整激活码。'],
    download:'先下载 Windows 版本'
  },
  en:{
    eyebrow:'PERSONAL v1 LICENSE',title:'One purchase. Perpetual use of GrowthMap Personal v1.',
    lead:'Unlock unlimited active projects on up to 2 personal devices. Both prices include the same Personal v1 license.',
    plansLabel:'Choose a Personal v1 option',
    early:'Early',earlyBadge:'First 50 worldwide',earlyPrice:'US$10',earlyBody:'One-time payment. Places are assigned after confirmed payment and successful license fulfillment; opening checkout does not reserve one.',buyEarly:'Buy Early — US$10',
    standard:'Standard',standardBadge:'From purchase 51',standardPrice:'US$29',standardBody:'One-time payment. This price begins after Early places are filled and includes the exact same license.',buyStandard:'Buy Standard — US$29',
    includedTitle:'Personal v1 includes',included:['Perpetual Personal v1 license','Unlimited simultaneously active projects','Up to 2 personal devices','Future Personal v1 updates'],
    flowTitle:'Purchase and activation',flow:['Complete an Early or Standard purchase on Whop.','Open the GrowthMap License Experience inside Whop.','Copy the GM1 activation key shown only to your verified account.','Enter the complete key in the Windows desktop app.'],
    download:'Download the Windows version first'
  }
};
