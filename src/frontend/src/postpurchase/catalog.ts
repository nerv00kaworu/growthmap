import { Locale, resolveLocale } from "@/i18n/catalog";

export const POST_PURCHASE_STATES = ["success", "delivery-pending", "recovered", "refunded", "disputed", "outage"] as const;
export type PostPurchaseState = (typeof POST_PURCHASE_STATES)[number];

const zhTW = {
  title: "購買後協助",
  successTitle: "授權已備妥",
  successBody: "授權碼僅在你主動顯示後出現。請立即建立離線備份；本頁不會宣稱已寄出電子郵件。",
  pendingTitle: "授權仍在處理中",
  pendingBody: "付款結果可能已完成，但授權交付尚未確認。請稍後重試；重試不會再次付款。",
  recoveredTitle: "授權已復原",
  recoveredBody: "已找到可用的既有授權。請主動顯示並建立新的離線備份。",
  refundedTitle: "此訂單已退款",
  refundedBody: "授權已終止，不能重新啟用。若退款狀態有誤，請附上案件識別碼聯絡支援。",
  disputedTitle: "此訂單有爭議或扣款退回",
  disputedBody: "授權已終止，不能重新啟用。請透過付款服務商處理爭議，或附上案件識別碼聯絡支援。",
  outageTitle: "服務暫時無法使用",
  outageBody: "請保留本頁，不要重複付款。稍後再重試授權狀態；既有離線備份不受影響。",
  reveal: "顯示授權碼",
  revealing: "正在安全取得授權碼…",
  cancelReveal: "取消取得授權碼",
  revealFallback: "目前無法取得授權碼。請稍後重試或使用支援入口。",
  hide: "隱藏授權碼",
  copyKey: "複製授權碼",
  downloadKey: "下載離線備份",
  backup: "將備份存放在只有你能存取的位置。不要放入網址、查詢參數、聊天或公開紀錄。",
  unavailableKey: "目前沒有可顯示的授權碼。請使用復原或支援入口。",
  copied: "已複製。請安全保存。",
  copyFallback: "無法使用剪貼簿。請從已顯示的欄位手動複製。",
  downloaded: "離線備份已下載。",
  downloadFallback: "瀏覽器無法下載。請複製已顯示的授權碼並自行存入安全檔案。",
  retry: "重試狀態",
  recovery: "復原授權",
  devices: "管理裝置",
  refund: "退款協助",
  support: "聯絡支援",
  unavailable: "目前未連接安全的後端入口。",
  correlation: "案件識別碼",
  copyCorrelation: "複製案件識別碼",
  correlationUnavailable: "案件識別碼不可用",
} as const;
type PostPurchaseKey = keyof typeof zhTW;
type Catalog = Readonly<Record<PostPurchaseKey, string>>;

const zhCN: Catalog = {
  title: "购买后协助", successTitle: "授权已就绪", successBody: "授权码仅在你主动显示后出现。请立即建立离线备份；本页不会声称已发送电子邮件。",
  pendingTitle: "授权仍在处理中", pendingBody: "付款结果可能已完成，但授权交付尚未确认。请稍后重试；重试不会再次付款。",
  recoveredTitle: "授权已恢复", recoveredBody: "已找到可用的现有授权。请主动显示并建立新的离线备份。",
  refundedTitle: "此订单已退款", refundedBody: "授权已终止，不能重新激活。若退款状态有误，请附上案件识别码联系支持。",
  disputedTitle: "此订单有争议或扣款退回", disputedBody: "授权已终止，不能重新激活。请通过付款服务商处理争议，或附上案件识别码联系支持。",
  outageTitle: "服务暂时不可用", outageBody: "请保留本页，不要重复付款。稍后重试授权状态；现有离线备份不受影响。",
  reveal: "显示授权码", revealing: "正在安全获取授权码…", cancelReveal: "取消获取授权码", revealFallback: "目前无法获取授权码。请稍后重试或使用支持入口。", hide: "隐藏授权码", copyKey: "复制授权码", downloadKey: "下载离线备份",
  backup: "将备份存放在只有你能访问的位置。不要放入网址、查询参数、聊天或公开记录。", unavailableKey: "目前没有可显示的授权码。请使用恢复或支持入口。",
  copied: "已复制。请安全保存。", copyFallback: "无法使用剪贴板。请从已显示的字段手动复制。", downloaded: "离线备份已下载。",
  downloadFallback: "浏览器无法下载。请复制已显示的授权码并自行存入安全文件。", retry: "重试状态", recovery: "恢复授权", devices: "管理设备",
  refund: "退款协助", support: "联系支持", unavailable: "目前未连接安全的后端入口。", correlation: "案件识别码", copyCorrelation: "复制案件识别码", correlationUnavailable: "案件识别码不可用",
};
const en: Catalog = {
  title: "Post-purchase help", successTitle: "Your license is ready", successBody: "The activation key appears only after you explicitly reveal it. Make an offline backup now; this page does not claim that an email was sent.",
  pendingTitle: "License delivery is still pending", pendingBody: "Payment may be complete, but license delivery is not confirmed. Retry later; retrying will not charge you again.",
  recoveredTitle: "License recovered", recoveredBody: "An existing license is available. Explicitly reveal it and make a new offline backup.",
  refundedTitle: "This order was refunded", refundedBody: "The license is terminated and cannot be reactivated. If this is incorrect, contact support with the case ID.",
  disputedTitle: "This order is disputed or charged back", disputedBody: "The license is terminated and cannot be reactivated. Resolve the dispute with the payment provider or contact support with the case ID.",
  outageTitle: "Service temporarily unavailable", outageBody: "Keep this page and do not pay again. Retry license status later; existing offline backups are unaffected.",
  reveal: "Reveal activation key", revealing: "Securely retrieving activation key…", cancelReveal: "Cancel key retrieval", revealFallback: "The activation key is currently unavailable. Retry later or use support.", hide: "Hide activation key", copyKey: "Copy activation key", downloadKey: "Download offline backup",
  backup: "Store the backup somewhere only you can access. Never put it in a URL, query string, chat, or public log.", unavailableKey: "No activation key is available. Use recovery or support.",
  copied: "Copied. Store it safely.", copyFallback: "Clipboard is unavailable. Manually copy from the revealed field.", downloaded: "Offline backup downloaded.",
  downloadFallback: "Download is unavailable. Copy the revealed key and save it in a secure file.", retry: "Retry status", recovery: "Recover license", devices: "Manage devices",
  refund: "Refund help", support: "Contact support", unavailable: "No secure backend entry is connected yet.", correlation: "Case ID", copyCorrelation: "Copy case ID", correlationUnavailable: "Case ID unavailable",
};
const catalogs: Readonly<Record<Locale, Catalog>> = { "zh-TW": zhTW, "zh-CN": zhCN, en };
export function postPurchaseTranslate(locale: unknown, key: PostPurchaseKey): string { return catalogs[resolveLocale(locale)][key]; }
export function stateMessageKeys(state: PostPurchaseState): readonly [PostPurchaseKey, PostPurchaseKey] {
  const map: Record<PostPurchaseState, readonly [PostPurchaseKey, PostPurchaseKey]> = {
    success: ["successTitle", "successBody"], "delivery-pending": ["pendingTitle", "pendingBody"], recovered: ["recoveredTitle", "recoveredBody"],
    refunded: ["refundedTitle", "refundedBody"], disputed: ["disputedTitle", "disputedBody"], outage: ["outageTitle", "outageBody"],
  };
  return map[state];
}
