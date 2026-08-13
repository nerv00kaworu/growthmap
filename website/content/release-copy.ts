import type {Locale} from './i18n';

export type ReleaseCopy={
  eyebrow:string; title:string; lead:string; cta:string; platformSuffix:string;
  fields:{version:string;size:string;platform:string};
  installTitle:string; installSteps:string[];
  requirementsTitle:string; requirements:string;
  warningTitle:string; warning:string;
  updateTitle:string; updateBody:string;
  license:string;
};

export const releaseCopy:Record<Locale,ReleaseCopy>={
  'zh-TW':{
    eyebrow:'WINDOWS 下載',
    title:'下載 GrowthMap Personal v1',
    lead:'適用於 Windows x64。下載安裝程式後，即可開始建立你的本機專案地圖。',
    cta:'下載 Windows 安裝程式',
    platformSuffix:'Windows x64',
    fields:{version:'目前版本',size:'下載大小',platform:'適用系統'},
    installTitle:'安裝方式',
    installSteps:['下載安裝程式。','開啟下載的檔案並依畫面完成安裝。','啟動 GrowthMap；若已有授權碼，可在程式內貼上並啟用。'],
    requirementsTitle:'使用前請確認',
    requirements:'目前支援 Windows x64，不支援 Windows ARM。專案資料預設保存在你的電腦上。',
    warningTitle:'Windows 安全提示',
    warning:'目前安裝程式尚未簽章，因此 Windows 可能顯示「未知的發行者」或 SmartScreen 提示。請確認檔案是從 growthmap.work 下載；不需要關閉 Windows 安全功能。',
    updateTitle:'日後如何更新',
    updateBody:'新版發布後，回到本頁下載新版安裝程式並直接覆蓋安裝。既有 Personal v1 授權、裝置身分與本機專案資料都會保留。',
    license:'查看 Personal v1 授權與購買'
  },
  'zh-CN':{
    eyebrow:'WINDOWS 下载',
    title:'下载 GrowthMap Personal v1',
    lead:'适用于 Windows x64。下载安装程序后，即可开始建立你的本地项目地图。',
    cta:'下载 Windows 安装程序',
    platformSuffix:'Windows x64',
    fields:{version:'当前版本',size:'下载大小',platform:'适用系统'},
    installTitle:'安装方式',
    installSteps:['下载安装程序。','打开下载的文件并按画面提示完成安装。','启动 GrowthMap；如已有激活码，可在程序内粘贴并激活。'],
    requirementsTitle:'使用前请确认',
    requirements:'目前支持 Windows x64，不支持 Windows ARM。项目数据默认保存在你的电脑上。',
    warningTitle:'Windows 安全提示',
    warning:'目前安装程序尚未签名，因此 Windows 可能显示“未知发布者”或 SmartScreen 提示。请确认文件来自 growthmap.work；无需关闭 Windows 安全功能。',
    updateTitle:'以后如何更新',
    updateBody:'新版本发布后，回到本页下载新版安装程序并直接覆盖安装。现有 Personal v1 授权、设备身份和本地项目数据都会保留。',
    license:'查看 Personal v1 授权与购买'
  },
  en:{
    eyebrow:'WINDOWS DOWNLOAD',
    title:'Download GrowthMap Personal v1',
    lead:'For Windows x64. Download the installer and start building your local project map.',
    cta:'Download the Windows installer',
    platformSuffix:'Windows x64',
    fields:{version:'Current version',size:'Download size',platform:'System'},
    installTitle:'How to install',
    installSteps:['Download the installer.','Open the downloaded file and follow the installation prompts.','Launch GrowthMap. If you have a license key, paste it into the app to activate.'],
    requirementsTitle:'Before you begin',
    requirements:'Windows x64 is currently supported; Windows ARM is not. Project data stays on your computer by default.',
    warningTitle:'Windows security notice',
    warning:'The installer is currently unsigned, so Windows may show “Unknown Publisher” or a SmartScreen notice. Make sure the file came from growthmap.work. You do not need to disable Windows security features.',
    updateTitle:'How future updates work',
    updateBody:'When a new version is released, return to this page and install the new version over the existing app. Your Personal v1 license, device identity, and local project data will remain in place.',
    license:'View Personal v1 licensing and purchase'
  }
};
