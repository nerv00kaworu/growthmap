import type {Locale} from './i18n';

type HomeCopy={
  eyebrow:string;title:string;lead:string;primary:string;secondary:string;micro:string;
  demoLabel:string;overviewLabel:string;demoNote:string;play:string;pause:string;
  pathsEyebrow:string;pathsTitle:string;pathsLead:string;
  paths:{label:string;title:string;body:string;flow:string[]}[];converge:string;
  governanceEyebrow:string;governanceTitle:string;
  steps:{label:string;title:string;body:string}[];
  exampleEyebrow:string;exampleTitle:string;exampleBody:string;
  focusEyebrow:string;focusTitle:string;focusCards:{title:string;body:string}[];
  boundaryEyebrow:string;boundaryTitle:string;boundaries:{title:string;body:string}[];
  closing:string;closingLead:string;explore:string;freeTitle:string;freeBody:string;statusCta:string;tree:{label:string;type:string}[];
};

const zhTW:HomeCopy={
  eyebrow:'人類與 Agent 共用的專案地圖',
  title:'讓想法自然生長。',
  lead:'GrowthMap 是人類與 Agent 共用的視覺化專案工作區。你可以在 GUI 主導規劃，讓 AI 協助展開與深化；也可以在與 Agent 討論時，讓它把談到的目標、決策、任務與風險逐項整理成節點。',
  primary:'看看兩種使用方式',secondary:'查看專案範例',micro:'Windows 本機優先 · 不綁特定 Agent · 人類掌握正式專案內容',
  demoLabel:'概念示範 · 非實機畫面',overviewLabel:'概念總覽 · 非實機畫面',demoNote:'兩支動畫使用同一個「個人記帳 App」，只改變專案進入 GrowthMap 的方式。',play:'播放概念動畫',pause:'暫停概念動畫',
  pathsEyebrow:'兩條入口，同一張專案地圖',pathsTitle:'你可以操作地圖，也可以讓專案從對話中被記錄下來。',pathsLead:'GrowthMap 的重點不是單純生成分支，而是讓人類、AI 與 Agent 討論產生的專案脈絡，都持續成為可整理、可校正、可追溯的結構。',
  paths:[
    {label:'01 / GUI 主導',title:'人類控制地圖，AI 協助展開。',body:'人類在 GUI 建立節點、調整結構、選定主線與分支；需要時，使用 Expand 或 Deepen，請 AI 提出子節點、內容、風險與驗收建議。',flow:['人類操作 GUI','AI Expand / Deepen','人類採用與修改']},
    {label:'02 / AGENT 對話主導',title:'一邊討論，Agent 一邊把專案記成節點。',body:'與 Agent 討論需求、方向或實作時，Agent 將談到的目標、功能、決策、問題、任務與風險逐項寫入或提案到 GrowthMap，不讓重要脈絡留在聊天紀錄裡消失。',flow:['與 Agent 討論','辨識專案內容','逐項形成節點']}
  ],
  converge:'兩條路最後匯入同一張由人類治理的 GrowthMap，並持續接上實作成果與下一步。',
  governanceEyebrow:'共同的治理流程',governanceTitle:'記錄進地圖，不代表 Agent 自動決定專案。',
  steps:[
    {label:'01 / 輸入',title:'來自 GUI 或對話',body:'人類直接建立內容，或由 Agent 將討論中的專案資訊逐項整理出來。'},
    {label:'02 / 結構化',title:'變成有意義的節點',body:'目標、功能、任務、決策、風險、問題、資源與備註各自保留角色與關係。'},
    {label:'03 / 治理',title:'人類校正與決定主線',body:'調整內容與位置、審核提案、選定主線，讓正式地圖反映人類真正的判斷。'},
    {label:'04 / 回填',title:'實作成果接回節點',body:'把檔案、commit、測試、決策、風險與下一步，連回它所服務的專案內容。'}
  ],
  exampleEyebrow:'具體範例',exampleTitle:'例如：你想做一款個人記帳 App。',exampleBody:'不是只留下一張漂亮腦圖，而是把產品方向、工作拆解、關鍵決策與實作結果持續放在同一份脈絡裡。',
  focusEyebrow:'GrowthMap 的重點',focusTitle:'對話不再只是對話，而會持續累積成可用的專案脈絡。',
  focusCards:[
    {title:'討論內容逐項成為節點',body:'Agent 不只回答當下問題，也能把已確認的需求、決策、待辦、風險與問題整理回地圖，讓下一次討論從既有脈絡繼續。'},
    {title:'計畫與實作不再分家',body:'節點能一路連到協作者、修改檔案、commit、測試結果、剩餘風險與下一步，讓交接有脈絡可循。'}
  ],
  boundaryEyebrow:'誠實的產品邊界',boundaryTitle:'由你掌控的本機專案工作區。',
  boundaries:[
    {title:'專案資料留在本機',body:'桌面專案使用本機資料；公開網站不會接收你的專案內容。'},
    {title:'AI 提案不等於自動批准',body:'重要方向與判斷先由人類審核；授權也能限制到指定節點或分支。'},
    {title:'不假裝自動完成所有事',body:'GrowthMap 不會自行掃描 Git、執行 Agent、部署程式或取得檔案系統權限。'}
  ],
  closing:'讓專案不只開始，也能持續長成成果。',closingLead:'人類掌握方向，AI 與 Agent 在正確的位置協助。',explore:'探索功能',freeTitle:'永久 Free，不是試用版。',freeBody:'包含全部核心功能；同時可啟用一個專案。封存或刪除專案即可釋放名額；讀取、搜尋、匯出與備份功能仍保留。',statusCta:'查看下載狀態',tree:[{label:'個人記帳 App',type:'IDEA'},{label:'3 秒完成記帳',type:'GOAL'},{label:'快速新增支出',type:'FEATURE'},{label:'設計輸入流程',type:'TASK'},{label:'12 項測試通過',type:'READBACK'},{label:'本機優先儲存',type:'DECISION'},{label:'資料遺失',type:'RISK'}]
};

const zhCN:HomeCopy={
  eyebrow:'人类与 Agent 共用的项目地图',title:'让想法自然生长。',lead:'GrowthMap 是人类与 Agent 共用的可视化项目工作区。你可以在 GUI 主导规划，让 AI 协助展开与深化；也可以在与 Agent 讨论时，让它把谈到的目标、决策、任务与风险逐项整理成节点。',primary:'看看两种使用方式',secondary:'查看项目示例',micro:'Windows 本地优先 · 不绑定特定 Agent · 人类掌握正式项目内容',demoLabel:'概念演示 · 非实际界面',overviewLabel:'概念总览 · 非实际界面',demoNote:'两段动画使用同一个“个人记账 App”，只改变项目进入 GrowthMap 的方式。',play:'播放概念动画',pause:'暂停概念动画',pathsEyebrow:'两个入口，同一张项目地图',pathsTitle:'你可以操作地图，也可以让项目从对话中被记录下来。',pathsLead:'GrowthMap 的重点不是单纯生成分支，而是让人类、AI 与 Agent 讨论产生的项目脉络，持续成为可整理、可校正、可追溯的结构。',paths:[{label:'01 / GUI 主导',title:'人类控制地图，AI 协助展开。',body:'人类在 GUI 创建节点、调整结构、选定主线与分支；需要时使用 Expand 或 Deepen，请 AI 提出子节点、内容、风险与验收建议。',flow:['人类操作 GUI','AI Expand / Deepen','人类采用与修改']},{label:'02 / AGENT 对话主导',title:'一边讨论，Agent 一边把项目记成节点。',body:'与 Agent 讨论需求、方向或实现时，Agent 将谈到的目标、功能、决策、问题、任务与风险逐项写入或提案到 GrowthMap，不让重要脉络消失在聊天记录里。',flow:['与 Agent 讨论','识别项目内容','逐项形成节点']}],converge:'两条路径最终汇入同一张由人类治理的 GrowthMap，并持续连接实现成果与下一步。',governanceEyebrow:'共同的治理流程',governanceTitle:'记录进地图，不代表 Agent 自动决定项目。',steps:[{label:'01 / 输入',title:'来自 GUI 或对话',body:'人类直接创建内容，或由 Agent 将讨论中的项目信息逐项整理出来。'},{label:'02 / 结构化',title:'变成有意义的节点',body:'目标、功能、任务、决策、风险、问题、资源与备注各自保留角色与关系。'},{label:'03 / 治理',title:'人类校正并决定主线',body:'调整内容与位置、审核提案、选定主线，让正式地图反映人类真正的判断。'},{label:'04 / 回填',title:'实现成果接回节点',body:'把文件、commit、测试、决策、风险与下一步，连接回它所服务的项目内容。'}],exampleEyebrow:'具体示例',exampleTitle:'例如：你想做一款个人记账 App。',exampleBody:'不是只留下一张漂亮的脑图，而是把产品方向、工作拆解、关键决策与实现结果持续放在同一份脉络里。',focusEyebrow:'GrowthMap 的重点',focusTitle:'对话不再只是对话，而会持续累积成可用的项目脉络。',focusCards:[{title:'讨论内容逐项成为节点',body:'Agent 不只回答当下问题，也能把已确认的需求、决策、待办、风险与问题整理回地图，让下一次讨论从已有脉络继续。'},{title:'计划与实现不再分离',body:'节点能一路连接到协作者、修改文件、commit、测试结果、剩余风险与下一步，让交接有脉络可循。'}],boundaryEyebrow:'诚实的产品边界',boundaryTitle:'由你掌控的本地项目工作区。',boundaries:[{title:'项目数据留在本机',body:'桌面项目使用本地数据；公开网站不会接收你的项目内容。'},{title:'AI 提案不等于自动批准',body:'重要方向与判断先由人类审核；授权也能限制到指定节点或分支。'},{title:'不假装自动完成所有事',body:'GrowthMap 不会自行扫描 Git、执行 Agent、部署程序或取得文件系统权限。'}],closing:'让项目不只开始，也能持续生长为成果。',closingLead:'人类掌握方向，AI 与 Agent 在正确的位置协助。',explore:'探索功能',freeTitle:'永久 Free，不是试用版。',freeBody:'包含全部核心功能；同时可启用一个项目。归档或删除项目即可释放名额；读取、搜索、导出与备份功能仍保留。',statusCta:'查看下载状态',tree:[{label:'个人记账 App',type:'IDEA'},{label:'3 秒完成记账',type:'GOAL'},{label:'快速新增支出',type:'FEATURE'},{label:'设计输入流程',type:'TASK'},{label:'12 项测试通过',type:'READBACK'},{label:'本地优先存储',type:'DECISION'},{label:'数据丢失',type:'RISK'}]
};

const en:HomeCopy={
  eyebrow:'A SHARED PROJECT MAP FOR PEOPLE + AGENTS',title:'Let ideas grow naturally.',lead:'GrowthMap is a visual project workspace shared by people and agents. Lead planning in the GUI and use AI to expand or deepen it—or discuss the project with an agent and have goals, decisions, tasks, and risks recorded as structured nodes.',primary:'See the two workflows',secondary:'View the project example',micro:'Windows local-first · Agent-neutral · People govern the official project',demoLabel:'Concept demo · Not the production UI',overviewLabel:'Concept overview · Not the production UI',demoNote:'Both animations use the same personal-finance app; only the way it enters GrowthMap changes.',play:'Play concept animation',pause:'Pause concept animation',pathsEyebrow:'TWO ENTRIES, ONE PROJECT MAP',pathsTitle:'Work directly on the map—or let the project be captured from a conversation.',pathsLead:'GrowthMap is not simply a branch generator. It keeps project context created by people, AI, and agent conversations structured, correctable, and traceable over time.',paths:[{label:'01 / GUI-LED',title:'People control the map; AI helps it grow.',body:'Create nodes, reshape the structure, and choose mainlines and branches in the GUI. Use Expand or Deepen when you want AI suggestions for child nodes, content, risks, or acceptance checks.',flow:['Human edits the GUI','AI Expand / Deepen','Human adopts and revises']},{label:'02 / AGENT-CONVERSATION-LED',title:'Discuss the project while the agent records it as nodes.',body:'As you discuss requirements, direction, or implementation, the agent records or proposes goals, features, decisions, questions, tasks, and risks in GrowthMap instead of leaving critical context buried in chat.',flow:['Discuss with an agent','Identify project content','Create structured nodes']}],converge:'Both workflows converge on the same human-governed GrowthMap and continue into implementation evidence and next steps.',governanceEyebrow:'ONE GOVERNANCE LOOP',governanceTitle:'Being recorded on the map does not mean the agent decides the project.',steps:[{label:'01 / INPUT',title:'From the GUI or conversation',body:'People create content directly, or an agent structures project information from the discussion.'},{label:'02 / STRUCTURE',title:'Turn it into meaningful nodes',body:'Goals, features, tasks, decisions, risks, questions, resources, and notes keep distinct roles and relationships.'},{label:'03 / GOVERN',title:'People correct and choose the mainline',body:'Reshape content, review proposals, and choose the path that reflects human judgment.'},{label:'04 / READ BACK',title:'Connect implementation to its node',body:'Return files, commits, tests, decisions, risks, and next steps to the project content they serve.'}],exampleEyebrow:'CONCRETE EXAMPLE',exampleTitle:'For example: you want to build a personal-finance app.',exampleBody:'The result is not merely a nice mind map. Product direction, work breakdown, key decisions, and implementation evidence stay connected in one context.',focusEyebrow:'WHAT MAKES GROWTHMAP DIFFERENT',focusTitle:'Conversation becomes durable, usable project context.',focusCards:[{title:'Discussion becomes structured nodes',body:'An agent can do more than answer the current question: confirmed requirements, decisions, todos, risks, and open questions return to the map so the next conversation starts with context.'},{title:'Planning and implementation stay connected',body:'A node can lead to collaborators, changed files, commits, test results, remaining risks, and next steps for a traceable handoff.'}],boundaryEyebrow:'HONEST PRODUCT BOUNDARIES',boundaryTitle:'A local project workspace under your control.',boundaries:[{title:'Project data stays local',body:'The desktop workspace uses local project data; the public website does not receive project content.'},{title:'AI proposals are not automatic approval',body:'People review judgment-sensitive direction; grants can also be scoped to specific nodes or branches.'},{title:'No pretend automation',body:'GrowthMap does not scan Git, execute agents, deploy software, or acquire filesystem authority by itself.'}],closing:'Help projects do more than start—help them grow into outcomes.',closingLead:'People lead; AI and agents assist in the right place.',explore:'Explore features',freeTitle:'Free forever—not a trial.',freeBody:'All core features with 1 active project at a time. Archive or delete to free the seat; reading, search, export, and backup remain available.',statusCta:'View download status',tree:[{label:'Personal-finance app',type:'IDEA'},{label:'Log an expense in 3 seconds',type:'GOAL'},{label:'Quick expense entry',type:'FEATURE'},{label:'Design the input flow',type:'TASK'},{label:'12 tests passed',type:'READBACK'},{label:'Local-first storage',type:'DECISION'},{label:'Data-loss risk',type:'RISK'}]
};

export const homeContent:Record<Locale,HomeCopy>={'zh-TW':zhTW,'zh-CN':zhCN,en};
