import type {Locale} from './i18n';import type {ProofSection} from './proof-content';
export const integration:Record<Locale,ProofSection>={
'zh-TW':{eyebrow:'INTEGRATION STATUS',title:'相容是一份本機協議，不是一串尚未驗證的品牌 Logo。',lead:'GrowthMap 不提供公開雲端 Agent API。整合發生在你的電腦上：工具必須能使用 loopback REST，或透過 CLI／MCP stdio 薄轉接器處理 grant、revision、receipt 與衝突；目前不是 Cursor、Claude Desktop 或其他具名工具的一鍵官方整合。',sections:[{title:'Available now',items:[{title:'本機 REST/JSON v1',body:'127.0.0.1 上的 /agent/v1 提供 capabilities、project、graph、context、proposal、batch、event 與 readback；不對公網開放。',status:'AVAILABLE NOW'},{title:'通用 CLI 與 MCP stdio',body:'兩者只轉接同一份 REST truth，不直接讀取 SQLite，也不取得 filesystem、shell、Git、部署或憑證權限。',status:'AVAILABLE NOW'},{title:'受治理的協作契約',body:'read／propose／write grant、project／exact-node／branch-descendant scope、人工核准、revision 409、atomic batch、idempotent receipt 與實作 readback 已存在。',status:'AVAILABLE NOW'},{title:'單機協作邊界',body:'同一個 Windows 本機工作區可由人類與多個相容 Agent 使用；多人即時同步、共享伺服器、P2P 與 Git-based 地圖同步目前尚未提供。',status:'AVAILABLE NOW'}]},{title:'Prototype',items:[{title:'具名 Agent 接入',body:'Hermes、Claude Code、Codex、OpenCode 可依標準 REST，或在支援 MCP stdio 的環境進行協議整合；目前沒有官方專用 adapter、開箱即用設定或認證矩陣。Cursor 與 Claude Desktop 也不在已驗證的一鍵整合清單。',status:'PROTOTYPE'},{title:'Context Packet 契約',body:'執行中的 API 已回傳 target、ancestors、children、decisions、constraints、risks、relations、revision 與 snapshot digest；網站先公開最小範例，尚未發行獨立 JSON Schema 套件。',status:'PROTOTYPE'}]},{title:'Planned',items:[{title:'版本化開發者套件',body:'公開 Context Packet JSON Schema、完整 request/response 範例、各工具安裝指南與 conformance tests。',status:'PLANNED'}]},{title:'最小 Context Packet',items:[{title:'Example',body:'{"target":{"id":"payment-module","revision":12},"objective":"define release gates","ancestors":["product-positioning","business-model"],"constraints":["no public payment"],"risks":["stale decision"],"project_revision":41,"snapshot_digest":"sha256:…"}',evidence:'示意欄位；不是即時專案資料'}]}]},
'zh-CN':{eyebrow:'INTEGRATION STATUS',title:'兼容是一份本地协议，不是一串尚未验证的品牌 Logo。',lead:'GrowthMap 不提供公开云端 Agent API。集成发生在你的电脑上：工具必须能使用 loopback REST，或通过 CLI／MCP stdio 薄适配器处理 grant、revision、receipt 与冲突。',sections:[{title:'Available now',items:[{title:'本地 REST/JSON v1',body:'127.0.0.1 上的 /agent/v1 提供 capabilities、project、graph、context、proposal、batch、event 与 readback，不对公网开放。',status:'AVAILABLE NOW'},{title:'通用 CLI 与 MCP stdio',body:'两者只适配同一份 REST truth，不直接读取 SQLite，也不取得 filesystem、shell、Git、部署或凭证权限。',status:'AVAILABLE NOW'},{title:'受治理的协作契约',body:'read／propose／write grant、project／exact-node／branch-descendant scope、人工批准、revision 409、atomic batch、idempotent receipt 与实现 readback 已存在。',status:'AVAILABLE NOW'}]},{title:'Prototype',items:[{title:'具名 Agent 接入',body:'Hermes、Claude Code、Codex、OpenCode 可按标准 REST，或在支持 MCP stdio 的环境进行协议集成；目前没有官方专用 adapter、开箱即用设置或认证矩阵。',status:'PROTOTYPE'},{title:'Context Packet 契约',body:'运行中的 API 已返回 target、ancestors、children、decisions、constraints、risks、relations、revision 与 snapshot digest；网站先公开最小示例，尚未发布独立 JSON Schema 包。',status:'PROTOTYPE'}]},{title:'Planned',items:[{title:'版本化开发者套件',body:'公开 Context Packet JSON Schema、完整请求/响应示例、各工具安装指南与 conformance tests。',status:'PLANNED'}]},{title:'最小 Context Packet',items:[{title:'Example',body:'{"target":{"id":"payment-module","revision":12},"objective":"define release gates","ancestors":["product-positioning","business-model"],"constraints":["no public payment"],"risks":["stale decision"],"project_revision":41,"snapshot_digest":"sha256:…"}',evidence:'示意字段；不是实时项目数据'}]}]},
en:{eyebrow:'INTEGRATION STATUS',title:'Compatibility is a local protocol, not a row of unverified logos.',lead:'GrowthMap does not expose a public cloud Agent API. Integration happens on your computer: a tool must use loopback REST or the CLI/MCP stdio thin adapters and honor grants, revisions, receipts, and conflicts.',sections:[{title:'Available now',items:[{title:'Local REST/JSON v1',body:'/agent/v1 on 127.0.0.1 exposes capabilities, project, graph, context, proposal, batch, event, and readback. It is not public internet API.',status:'AVAILABLE NOW'},{title:'Generic CLI and MCP stdio',body:'Both adapt the same REST truth. They do not read SQLite directly or acquire filesystem, shell, Git, deployment, or credential authority.',status:'AVAILABLE NOW'},{title:'Governed collaboration contract',body:'read/propose/write grants; project, exact-node, and branch-descendant scopes; human review; revision 409; atomic batches; idempotent receipts; and implementation readback exist now.',status:'AVAILABLE NOW'}]},{title:'Prototype',items:[{title:'Named Agent connection',body:'Hermes, Claude Code, Codex, and OpenCode may integrate through standard REST or an MCP-stdio-capable environment. There is no official dedicated adapter, zero-config setup, or certification matrix yet.',status:'PROTOTYPE'},{title:'Context Packet contract',body:'The running API returns target, ancestors, children, decisions, constraints, risks, relations, revisions, and a snapshot digest. This site shows a minimum example; no standalone JSON Schema package is published yet.',status:'PROTOTYPE'}]},{title:'Planned',items:[{title:'Versioned developer kit',body:'A public Context Packet JSON Schema, complete request/response examples, per-tool setup guides, and conformance tests.',status:'PLANNED'}]},{title:'Minimum Context Packet',items:[{title:'Example',body:'{"target":{"id":"payment-module","revision":12},"objective":"define release gates","ancestors":["product-positioning","business-model"],"constraints":["no public payment"],"risks":["stale decision"],"project_revision":41,"snapshot_digest":"sha256:…"}',evidence:'Illustrative fields; not live project data'}]}]}}
;
export const securityProof:Record<Locale,ProofSection>={
'zh-TW':{
  eyebrow:'LOCAL-FIRST SECURITY',
  title:'專案資料留在本機，Agent 權限保持在清楚邊界內。',
  lead:'GrowthMap 是以 Windows 本機工作區為核心的桌面工具。專案地圖與 SQLite 資料庫預設留在你的電腦上；公開網站不會接收你的專案資料。只有你明確設定並使用外部 AI 服務時，相關請求才會送往該服務。',
  sections:[
    {title:'技術架構與本機資料',items:[
      {title:'在地技術棧',body:'桌面介面以 Next.js、React Flow 與 Zustand 建構，後端使用 FastAPI、SQLAlchemy 與 SQLite。前後端透過本機 sidecar 協作，不需要把專案圖譜放到 GrowthMap 的雲端。'},
      {title:'SQLite 工作區',body:'預設資料庫位於 Electron userData；你也可以選擇 Windows 本機資料夾。為避免鎖定、延遲與同步衝突，WSL、UNC、網路磁碟與雲端同步資料夾不作為工作區。'},
      {title:'匯出前請確認內容',body:'JSON 與 Markdown 會包含專案節點及其內容；JSON 也可能包含操作紀錄中的 payload 與 file_paths。Provider API key 不會被加入匯出檔，但你自行寫入節點的路徑、token 或敏感文字仍會隨內容匯出。'}
    ]},
    {title:'憑證與 Agent 授權',items:[
      {title:'Provider API Key',body:'Windows 桌面版使用 DPAPI 封裝金鑰；SQLite 只保存 provider metadata 與 secret 名稱，不保存明文 API key。若作業系統安全儲存不可用，GrowthMap 會拒絕保存。'},
      {title:'Grant Token',body:'Grant token 只在建立時顯示一次；資料庫保存 prefix、salt 與強雜湊。Grant 可設定範圍與到期時間，也能隨時撤銷；過期或撤銷後便不能繼續存取。'},
      {title:'最小權限原則',body:'Agent 可取得 read、propose 或 scoped write 權限，並限制在指定專案、節點或分支範圍。Propose 需經人類批准；scoped write 只能在授權範圍內操作，並留下可追溯的 receipt 與 action history。'}
    ]},
    {title:'網路與執行邊界',items:[
      {title:'本機連線',body:'桌面介面只連線到隨機的 127.0.0.1 sidecar；Agent Port 也以 loopback 與可信 Host 為邊界，不是公開雲端 API。外部導航與新視窗預設受限制。'},
      {title:'Agent 不會自動取得系統權限',body:'Agent Port 只提供受限的專案圖譜操作，不授予 filesystem、shell、Git、部署、付款、憑證或任意資料庫存取權。這些能力若存在，仍由你使用的外部 Agent 工具自行管理。'},
      {title:'對外連線必須有明確目的',body:'GrowthMap 不配置第三方遙測或崩潰資料上傳。只有你主動使用並設定的外部服務才可能連線；公開網站與本機專案工作區彼此獨立。'}
    ]},
    {title:'備份、復原與產品邊界',items:[
      {title:'管理備份',body:'備份存放在目前工作區的 backups/，包含 SQLite 快照、SHA-256、大小與 manifest。匯入、還原及 migration 等高風險流程會先驗證或建立備份證據。'},
      {title:'驗證失敗就停止寫入',body:'當 migration 或復原證據不一致時，GrowthMap 會 fail closed，進入唯讀或復原流程，而不是在狀態不明時繼續修改資料。'},
      {title:'目前的產品範圍',body:'目前核心是單一 Windows 本機工作區中的人類與相容 Agent 協作。多人即時同步、雲端共享工作區、P2P 與 Git-based 地圖同步不在目前版本範圍內。'}
    ]}
  ]
},
'zh-CN':{
  eyebrow:'LOCAL-FIRST SECURITY',
  title:'项目数据留在本地，Agent 权限保持在清晰边界内。',
  lead:'GrowthMap 是以 Windows 本地工作区为核心的桌面工具。项目地图与 SQLite 数据库默认留在你的电脑上；官方网站不会接收你的项目数据。只有你明确设置并使用外部 AI 服务时，相关请求才会发送给该服务。',
  sections:[
    {title:'技术架构与本地数据',items:[
      {title:'本地技术栈',body:'桌面界面以 Next.js、React Flow 与 Zustand 构建，后端使用 FastAPI、SQLAlchemy 与 SQLite。前后端通过本地 sidecar 协作，不需要把项目图谱放到 GrowthMap 云端。'},
      {title:'SQLite 工作区',body:'默认数据库位于 Electron userData；你也可以选择 Windows 本地文件夹。为避免锁定、延迟与同步冲突，WSL、UNC、网络磁盘与云同步文件夹不作为工作区。'},
      {title:'导出前请确认内容',body:'JSON 与 Markdown 会包含项目节点及其内容；JSON 也可能包含操作记录中的 payload 与 file_paths。Provider API key 不会加入导出文件，但你自行写入节点的路径、token 或敏感文字仍会随内容导出。'}
    ]},
    {title:'凭证与 Agent 授权',items:[
      {title:'Provider API Key',body:'Windows 桌面版使用 DPAPI 封装密钥；SQLite 只保存 provider metadata 与 secret 名称，不保存明文 API key。若操作系统安全存储不可用，GrowthMap 会拒绝保存。'},
      {title:'Grant Token',body:'Grant token 只在创建时显示一次；数据库保存 prefix、salt 与强哈希。Grant 可设置范围与到期时间，也可随时撤销；过期或撤销后便不能继续访问。'},
      {title:'最小权限原则',body:'Agent 可取得 read、propose 或 scoped write 权限，并限制在指定项目、节点或分支范围。Propose 需经人工批准；scoped write 只能在授权范围内操作，并留下可追溯的 receipt 与 action history。'}
    ]},
    {title:'网络与执行边界',items:[
      {title:'本地连接',body:'桌面界面只连接到随机的 127.0.0.1 sidecar；Agent Port 也以 loopback 与可信 Host 为边界，并非公开云端 API。外部导航与新窗口默认受限制。'},
      {title:'Agent 不会自动取得系统权限',body:'Agent Port 只提供受限的项目图谱操作，不授予 filesystem、shell、Git、部署、支付、凭证或任意数据库访问权。这些能力若存在，仍由你使用的外部 Agent 工具自行管理。'},
      {title:'对外连接必须有明确目的',body:'GrowthMap 不配置第三方遥测或崩溃数据上传。只有你主动使用并设置的外部服务才可能联网；官方网站与本地项目工作区彼此独立。'}
    ]},
    {title:'备份、恢复与产品边界',items:[
      {title:'管理备份',body:'备份存放在当前工作区的 backups/，包含 SQLite 快照、SHA-256、大小与 manifest。导入、还原及 migration 等高风险流程会先验证或建立备份证据。'},
      {title:'验证失败就停止写入',body:'当 migration 或恢复证据不一致时，GrowthMap 会 fail closed，进入只读或恢复流程，而不是在状态不明时继续修改数据。'},
      {title:'当前产品范围',body:'当前核心是单一 Windows 本地工作区中的人类与兼容 Agent 协作。多人实时同步、云端共享工作区、P2P 与 Git-based 地图同步不在当前版本范围内。'}
    ]}
  ]
},
en:{
  eyebrow:'LOCAL-FIRST SECURITY',
  title:'Project data stays local. Agent authority stays within explicit boundaries.',
  lead:'GrowthMap is a desktop tool centered on a local Windows workspace. Your project map and SQLite database remain on your computer by default, and the public website does not receive project data. Requests leave the machine only when you explicitly configure and use an external AI service.',
  sections:[
    {title:'Architecture and local data',items:[
      {title:'Local application stack',body:'The desktop interface uses Next.js, React Flow, and Zustand. The backend uses FastAPI, SQLAlchemy, and SQLite. They communicate through a local sidecar, so the project graph does not need to live in a GrowthMap cloud service.'},
      {title:'SQLite workspace',body:'The default database lives under Electron userData, and you may choose another local Windows folder. WSL, UNC paths, network drives, and cloud-sync folders are not accepted as workspaces to avoid locking, latency, and synchronization conflicts.'},
      {title:'Review exports before sharing',body:'JSON and Markdown contain project nodes and their content. JSON may also include action payloads and file_paths. Provider API keys are not added, but paths, tokens, or sensitive text that you place inside nodes remain part of the exported content.'}
    ]},
    {title:'Credentials and Agent grants',items:[
      {title:'Provider API keys',body:'The Windows desktop wraps keys with DPAPI. SQLite stores provider metadata and a secret name, not the plaintext API key. GrowthMap refuses to save a key when operating-system secure storage is unavailable.'},
      {title:'Grant tokens',body:'A grant token is shown once when created; the database stores a prefix, salt, and strong hash. Grants may be scoped, expired, or revoked, and cannot be used after expiry or revocation.'},
      {title:'Least authority',body:'An Agent may receive read, propose, or scoped write access limited to a project, node, or branch. Proposals require human approval. Scoped writes operate only inside the grant boundary and leave traceable receipts and action history.'}
    ]},
    {title:'Network and execution boundaries',items:[
      {title:'Local connections',body:'The desktop interface connects only to a random 127.0.0.1 sidecar. Agent Port is also bounded to loopback and trusted Hosts rather than exposed as a public cloud API. External navigation and new windows are restricted by default.'},
      {title:'No automatic system authority',body:'Agent Port exposes scoped project-map operations. It grants no filesystem, shell, Git, deployment, payment, credential, or arbitrary database access. If an external Agent tool has those powers, that tool remains responsible for managing them.'},
      {title:'Outbound connections need a clear purpose',body:'GrowthMap does not configure third-party telemetry or crash-data uploads. Only external services that you deliberately configure and use may receive requests; the public website and local project workspace remain separate.'}
    ]},
    {title:'Backup, recovery, and product scope',items:[
      {title:'Managed backups',body:'Backups live under backups/ in the active workspace and include a SQLite snapshot, SHA-256, size, and manifest. Higher-risk flows such as import, restore, and migration verify or create backup evidence first.'},
      {title:'Failed verification stops writes',body:'When migration or recovery evidence does not match, GrowthMap fails closed into a read-only or recovery path instead of continuing to modify data in an uncertain state.'},
      {title:'Current product scope',body:'The current core is collaboration between people and compatible Agents in one local Windows workspace. Real-time multi-user sync, cloud-shared workspaces, P2P, and Git-based map synchronization are outside the current version.'}
    ]}
  ]
}
};
