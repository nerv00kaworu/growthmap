import type {Locale} from './i18n';

type Plan={
  name:string;
  badge:string;
  summary:string;
  features:string[];
  quota:string;
  fit:string;
};

type BuyPlans={
  comparisonLead:string;
  plansLabel:string;
  free:Plan;
  personal:Plan&{price:string;allocation:string};
};

export const buyPlans={
  'zh-TW':{
    comparisonLead:'Free 已包含全部核心功能；購買授權主要解鎖不限啟用專案與兩台個人裝置。',
    plansLabel:'方案比較',
    free:{
      name:'Free',badge:'永久免費 · 全部核心功能',
      summary:'不是試用版，也沒有刪減核心功能。',
      features:['GUI 規劃；Tree、Graph、Branch、Mainline 與 Node','AI Expand 與 Deepen','與相容 Agent 協作、把討論記為節點，並讀回成果','匯出與備份'],
      quota:'可同時啟用 1 個專案。這不是只能建立或保存一個專案；封存或刪除目前啟用的專案即可釋放名額。達到上限後，讀取、搜尋、匯出與備份仍可使用。',
      fit:'適合一次專注推進一個啟用中專案。'
    },
    personal:{
      name:'Personal v1',badge:'v1 個人永久授權',
      summary:'包含 Free 全部功能；付費差異只在專案名額、裝置與授權更新。',
      features:['不限同時啟用的專案數量','授權簽發對象最多可使用 2 台個人裝置','Personal v1 永久授權，包含後續 Personal v1 更新'],
      quota:'不改變核心功能；解鎖的是不限啟用專案與個人裝置額度。',
      price:'US$10',
      allocation:'全球前 50 個付款確認（payment-confirmed）的名額為 US$10；第 51 個起為 US$29。報價（quote）不保留名額。',
      fit:'適合同時推進多個啟用中專案，或需要第二台個人裝置。'
    }
  },
  'zh-CN':{
    comparisonLead:'Free 已包含全部核心功能；购买授权主要解锁不限启用项目与两台个人设备。',
    plansLabel:'方案比较',
    free:{
      name:'Free',badge:'永久免费 · 全部核心功能',
      summary:'不是试用版，也没有删减核心功能。',
      features:['GUI 规划；Tree、Graph、Branch、Mainline 与 Node','AI Expand 与 Deepen','与兼容 Agent 协作、把讨论记为节点，并读回成果','导出与备份'],
      quota:'可同时启用 1 个项目。这不是只能创建或保存一个项目；归档或删除目前启用的项目即可释放名额。达到上限后，读取、搜索、导出与备份仍可使用。',
      fit:'适合一次专注推进一个启用中的项目。'
    },
    personal:{
      name:'Personal v1',badge:'v1 个人永久授权',
      summary:'包含 Free 全部功能；付费差异只在项目名额、设备与授权更新。',
      features:['不限同时启用的项目数量','授权签发对象最多可使用 2 台个人设备','Personal v1 永久授权，包含后续 Personal v1 更新'],
      quota:'不改变核心功能；解锁的是不限启用项目与个人设备额度。',
      price:'US$10',
      allocation:'全球前 50 个付款确认（payment-confirmed）的名额为 US$10；第 51 个起为 US$29。报价（quote）不保留名额。',
      fit:'适合同时推进多个启用中的项目，或需要第二台个人设备。'
    }
  },
  en:{
    comparisonLead:'Free already includes every core feature; purchasing a license primarily unlocks unlimited active projects and two personal devices.',
    plansLabel:'Compare plans',
    free:{
      name:'Free',badge:'Free forever · All core features',
      summary:'This is not a trial, and no core features are removed.',
      features:['GUI planning with Tree, Graph, Branch, Mainline, and Node','AI Expand and Deepen','Work with compatible agents, record discussions as nodes, and read outcomes back','Export and backup'],
      quota:'Keep 1 project active at a time. This does not mean you can create or store only one project: archive or delete the active project to free the slot. Reading, search, export, and backup remain available at the limit.',
      fit:'Best when you focus on one active project at a time.'
    },
    personal:{
      name:'Personal v1',badge:'Personal perpetual v1 license',
      summary:'Includes everything in Free; paid differences are limited to project capacity, devices, and license updates.',
      features:['Unlimited simultaneously active projects','Up to 2 personal devices for the license’s named issuer target','Perpetual Personal v1 license with future Personal v1 updates'],
      quota:'Core features do not change; the license unlocks unlimited active projects and the personal-device allowance.',
      price:'US$10',
      allocation:'The first 50 payment-confirmed allocations worldwide are US$10; allocation 51 onward is US$29. A quote does not reserve an allocation.',
      fit:'Best for running several active projects at once or using a second personal device.'
    }
  }
} satisfies Record<Locale,BuyPlans>;
