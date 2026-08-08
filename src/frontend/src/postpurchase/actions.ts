export type ActionResult = "ok" | "fallback";
export interface ClipboardPort { writeText(value: string): Promise<void> }
export interface DownloadPort {
  createTextFile(contents: string): string;
  trigger(url: string, filename: string): void;
  revoke(url: string): void;
}

export async function copySecret(value: string, clipboard: ClipboardPort | null | undefined): Promise<ActionResult> {
  if (!clipboard) return "fallback";
  try { await clipboard.writeText(value); return "ok"; } catch { return "fallback"; }
}
export function downloadSecret(value: string, port: DownloadPort | null | undefined): ActionResult {
  if (!port) return "fallback";
  let url: string | undefined;
  try {
    url = port.createTextFile(`${value}\n`);
    port.trigger(url, "growthmap-activation-key.txt");
    return "ok";
  } catch { return "fallback"; }
  finally { if (url) { try { port.revoke(url); } catch { /* best-effort cleanup */ } } }
}
export function browserDownloadPort(): DownloadPort | null {
  if (typeof document === "undefined" || typeof URL.createObjectURL !== "function") return null;
  return {
    createTextFile: (contents) => URL.createObjectURL(new Blob([contents], { type: "text/plain;charset=utf-8" })),
    trigger: (url, filename) => { const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.rel = "noopener"; anchor.click(); },
    revoke: (url) => URL.revokeObjectURL(url),
  };
}
