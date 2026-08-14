export const SUPPORTED_LOCALES = ["zh-TW", "zh-CN", "en"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";

export function resolveLocale(value: unknown): Locale {
  return typeof value === "string" && (SUPPORTED_LOCALES as readonly string[]).includes(value)
    ? (value as Locale)
    : DEFAULT_LOCALE;
}

const zhTW = {
  "locale.label": "語言",
  "locale.zh-TW": "繁體中文",
  "locale.zh-CN": "简体中文",
  "locale.en": "English",
  "project.selectLabel": "選擇專案",
  "project.selectPlaceholder": "選擇專案...",
  "branch.selectLabel": "選擇分支",
  "branch.main": "🌿 主線（main）",
  "branch.option": "🔀 方案線：{name}",
  "entitlement.checking": "Checking entitlement…",
  "entitlement.paid": "Paid · perpetual v{version} · unlimited",
  "entitlement.free": "Free · {count}/1 active project",
  "entitlement.readOnly": "Read-only extraction · exports available",
  "project.new": "+ 新專案",
  "more.title": "⋯ 更多操作",
  "more.tooltip": "更多操作",
  "search.placeholder": "🔍 搜尋節點...",
  "search.results": "{count} 個結果",
  "database.tooltip": "資料庫工作區",
  "llm.tooltip": "LLM Provider 設定",
  "shortcuts.tooltip": "鍵盤快捷鍵",
  "more.currentBranch": "目前方案線：{name}",
  "more.summary": "匯入匯出、復原與方案線管理",
  "export.spec": "📋 匯出規格",
  "export.markdown": "📄 匯出 Markdown",
  "export.json": "📤 匯出 JSON",
  "import.json": "📥 匯入 JSON",
  "undo": "↩ 復原",
  "llm.settings": "⚙️ LLM 設定",
  "license.import": "🔑 匯入 License",
  "activation.title": "啟用 GrowthMap",
  "activation.help": "付款在網頁完成。取得授權碼後貼在這裡，首次啟用完成即可由此裝置離線驗證。",
  "activation.placeholder": "GM1.…",
  "activation.activating": "啟用中…",
  "activation.unlock": "輸入授權碼解鎖",
  "activation.purchase": "前往購買網頁",
  "activation.boundary": "桌面程式不包含錢包、付款 SDK、Base RPC、收款地址或價格設定。",
  "updates.check": "⬆️ 檢查更新",
  "project.archive": "🗄️ 封存專案",
  "project.restore": "♻️ 恢復專案",
  "agent.sessions": "🤖 Agent 工作階段",
  "agent.port": "🔌 Agent Port",
  "shortcuts.menu": "⌨️ 快捷鍵",
  "branch.history": "🗂️ 方案線歷史",
  "danger.title": "危險操作",
  "branch.archiveNamed": "封存方案線：{name}",
  "branch.archiveUnavailable": "目前是主線，請先切到方案線後才能封存",
  "branch.mainCannotArchive": "主線不可封存",
  "branch.archiveConfirm": "確定封存方案線「{name}」？\n\n封存後不會刪除資料，可在方案線管理中查看歷史紀錄。",
  "branch.historyHelp": "包含建立、合併與封存紀錄；封存資料仍可追溯。",
  "branch.historyLoading": "讀取方案線歷史中…",
  "branch.historyEmpty": "此專案尚無方案線歷史。",
  "project.name": "專案名稱",
  "project.nameExample": "例：Fate Origin Agent",
  "project.description": "描述（選填）",
  "project.descriptionPlaceholder": "一句話描述",
  "common.create": "建立",
  "common.cancel": "取消",
  "loading.switchingBranch": "正在切換分支…",
  "loading.switchingProject": "正在切換專案…",
  "loading.syncing": "同步樹狀資料中",
  "shortcuts.title": "⌨️ 鍵盤快捷鍵",
  "shortcuts.escape": "取消選取 / 關閉面板",
  "shortcuts.delete": "刪除選取節點",
  "shortcuts.expand": "展開選取節點（AI）",
  "shortcuts.deepen": "深化選取節點（AI）",
  "shortcuts.undo": "復原",
  "error.export": "匯出失敗",
  "error.exportJson": "JSON 匯出失敗",
  "error.import": "匯入失敗",
  "toast.projectRestored": "✅ 專案已恢復",
  "toast.projectArchived": "✅ 專案已封存；資料仍可讀與匯出",
  "toast.licenseDesktopOnly": "License 匯入僅在桌面版提供",
  "toast.licenseImported": "✅ License 已驗證並匯入",
  "toast.purchaseDesktopOnly": "購買頁面僅在桌面版提供",
  "toast.activationDesktopOnly": "授權啟用僅在桌面版提供",
  "toast.activated": "✅ 授權已啟用，此裝置可離線驗證",
  "toast.imported": "✅ 匯入成功！",
  "confirm.deleteNode": "確定刪除此節點？",
} as const;

export type MessageKey = keyof typeof zhTW;
type Catalog = { readonly [K in MessageKey]: string };

const zhCN = {
  ...zhTW,
  "locale.label": "语言", "llm.tooltip": "LLM Provider 设置", "llm.settings": "⚙️ LLM 设置", "license.import": "🔑 导入 License", "activation.title": "启用 GrowthMap", "activation.boundary": "桌面应用不包含钱包、付款 SDK、Base RPC、收款地址或价格设置。", "project.selectLabel": "选择项目", "project.selectPlaceholder": "选择项目...", "branch.selectLabel": "选择分支",
  "branch.main": "🌿 主线（main）", "branch.option": "🔀 方案线：{name}", "project.new": "+ 新项目", "more.tooltip": "更多操作",
  "search.placeholder": "🔍 搜索节点...", "search.results": "{count} 个结果", "database.tooltip": "数据库工作区", "shortcuts.tooltip": "键盘快捷键",
  "more.currentBranch": "当前方案线：{name}", "more.summary": "导入导出、撤销与方案线管理", "export.spec": "📋 导出规格",
  "export.markdown": "📄 导出 Markdown", "export.json": "📤 导出 JSON", "import.json": "📥 导入 JSON", "undo": "↩ 撤销",
  "activation.help": "付款在网页完成。取得授权码后粘贴在这里，首次启用完成后此设备即可离线验证。", "activation.activating": "启用中…",
  "activation.unlock": "输入授权码解锁", "activation.purchase": "前往购买网页", "updates.check": "⬆️ 检查更新", "project.archive": "🗄️ 归档项目",
  "project.restore": "♻️ 恢复项目", "shortcuts.menu": "⌨️ 快捷键", "branch.history": "🗂️ 方案线历史", "danger.title": "危险操作",
  "branch.archiveNamed": "归档方案线：{name}", "branch.archiveUnavailable": "当前是主线，请先切换到方案线后再归档", "branch.mainCannotArchive": "主线不可归档",
  "branch.archiveConfirm": "确定归档方案线“{name}”？\n\n归档不会删除数据，可在方案线管理中查看历史记录。", "branch.historyHelp": "包含创建、合并与归档记录；归档数据仍可追溯。",
  "branch.historyLoading": "正在读取方案线历史…", "branch.historyEmpty": "此项目尚无方案线历史。", "project.name": "项目名称", "project.nameExample": "例：Fate Origin Agent",
  "project.description": "描述（选填）", "project.descriptionPlaceholder": "一句话描述", "common.create": "创建", "common.cancel": "取消",
  "loading.switchingBranch": "正在切换分支…", "loading.switchingProject": "正在切换项目…", "loading.syncing": "正在同步树状数据",
  "shortcuts.escape": "取消选择 / 关闭面板", "shortcuts.delete": "删除所选节点", "shortcuts.expand": "展开所选节点（AI）", "shortcuts.deepen": "深化所选节点（AI）", "shortcuts.undo": "撤销",
  "error.export": "导出失败", "error.exportJson": "JSON 导出失败", "error.import": "导入失败", "toast.projectRestored": "✅ 项目已恢复",
  "toast.projectArchived": "✅ 项目已归档；数据仍可读取与导出", "toast.licenseDesktopOnly": "License 导入仅在桌面版提供", "toast.licenseImported": "✅ License 已验证并导入",
  "toast.purchaseDesktopOnly": "购买页面仅在桌面版提供", "toast.activationDesktopOnly": "授权启用仅在桌面版提供", "toast.activated": "✅ 授权已启用，此设备可离线验证",
  "toast.imported": "✅ 导入成功！", "confirm.deleteNode": "确定删除此节点？",
} as const satisfies Catalog;

const en = {
  ...zhTW,
  "locale.label": "Language", "locale.zh-TW": "Traditional Chinese", "locale.zh-CN": "Simplified Chinese", "project.selectLabel": "Select project", "project.selectPlaceholder": "Select project...",
  "branch.selectLabel": "Select branch", "branch.main": "🌿 Main", "branch.option": "🔀 Scenario: {name}", "project.new": "+ New project", "more.title": "⋯ More actions", "more.tooltip": "More actions",
  "search.placeholder": "🔍 Search nodes...", "search.results": "{count} results", "database.tooltip": "Database workspace", "llm.tooltip": "LLM provider settings", "shortcuts.tooltip": "Keyboard shortcuts",
  "more.currentBranch": "Current scenario: {name}", "more.summary": "Import, export, undo, and scenario management", "export.spec": "📋 Export spec", "export.markdown": "📄 Export Markdown",
  "export.json": "📤 Export JSON", "import.json": "📥 Import JSON", "undo": "↩ Undo", "llm.settings": "⚙️ LLM settings", "license.import": "🔑 Import license", "activation.title": "Activate GrowthMap",
  "activation.help": "Payment is completed on the web. Paste the license key here; after first activation, this device can verify it offline.", "activation.activating": "Activating…", "activation.unlock": "Enter key to unlock",
  "activation.purchase": "Open purchase page", "activation.boundary": "The desktop app contains no wallet, payment SDK, Base RPC, payment address, or price configuration.", "updates.check": "⬆️ Check for updates",
  "project.archive": "🗄️ Archive project", "project.restore": "♻️ Restore project", "agent.sessions": "🤖 Agent sessions", "shortcuts.menu": "⌨️ Shortcuts", "branch.history": "🗂️ Scenario history",
  "danger.title": "Danger zone", "branch.archiveNamed": "Archive scenario: {name}", "branch.archiveUnavailable": "This is the main branch. Switch to a scenario before archiving.", "branch.mainCannotArchive": "Main cannot be archived",
  "branch.archiveConfirm": "Archive scenario “{name}”?\n\nArchiving does not delete data. Its history remains available in scenario management.", "branch.historyHelp": "Includes creation, merge, and archive records; archived data remains traceable.",
  "branch.historyLoading": "Loading scenario history…", "branch.historyEmpty": "This project has no scenario history.", "project.name": "Project name", "project.nameExample": "Example: Fate Origin Agent",
  "project.description": "Description (optional)", "project.descriptionPlaceholder": "One-line description", "common.create": "Create", "common.cancel": "Cancel", "loading.switchingBranch": "Switching branch…",
  "loading.switchingProject": "Switching project…", "loading.syncing": "Syncing tree data", "shortcuts.title": "⌨️ Keyboard shortcuts", "shortcuts.escape": "Clear selection / close panel", "shortcuts.delete": "Delete selected node",
  "shortcuts.expand": "Expand selected node (AI)", "shortcuts.deepen": "Deepen selected node (AI)", "shortcuts.undo": "Undo", "error.export": "Export failed", "error.exportJson": "JSON export failed", "error.import": "Import failed",
  "toast.projectRestored": "✅ Project restored", "toast.projectArchived": "✅ Project archived; data remains readable and exportable", "toast.licenseDesktopOnly": "License import is available only in the desktop app",
  "toast.licenseImported": "✅ License verified and imported", "toast.purchaseDesktopOnly": "The purchase page is available only in the desktop app", "toast.activationDesktopOnly": "Activation is available only in the desktop app",
  "toast.activated": "✅ License activated; this device can verify it offline", "toast.imported": "✅ Import complete!", "confirm.deleteNode": "Delete this node?",
} as const satisfies Catalog;

export const catalogs: Readonly<Record<Locale, Catalog>> = { "zh-TW": zhTW, "zh-CN": zhCN, en };
export type Translate = (key: MessageKey, values?: Readonly<Record<string, string | number>>) => string;
/** Locale-select a colocated message at boundaries where a stable catalog key would add no reuse. */
export function localize(locale: Locale, messages: Readonly<{ "zh-TW": string; "zh-CN": string; en: string }>): string {
  return messages[locale];
}
export function translate(locale: unknown, key: MessageKey, values: Readonly<Record<string, string | number>> = {}): string {
  return catalogs[resolveLocale(locale)][key].replace(/\{(\w+)\}/g, (token, name: string) => name in values ? String(values[name]) : token);
}
