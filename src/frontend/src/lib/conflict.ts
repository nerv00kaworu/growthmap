import { activeMsg } from "@/i18n/ui";
export type ConflictDraft = {
  nodeDraft?: string;
  suggestionInput?: string;
};

export type ConflictState = ConflictDraft & {
  visible: true;
  message: string;
};

/** Run one mutation. Revision conflicts are never replayed: refresh exactly once
 * and preserve local inputs so the UI can let the human reconcile explicitly. */
export async function runMutationWithConflict<T>(
  mutate: () => Promise<T>,
  refresh: () => Promise<void>,
  draft: ConflictDraft = {},
): Promise<{ value?: T; conflict?: ConflictState }> {
  try {
    return { value: await mutate() };
  } catch (error) {
    const status = typeof error === "object" && error !== null && "status" in error
      ? Number((error as { status: unknown }).status) : undefined;
    if (status !== 409) throw error;
    await refresh();
    return {
      conflict: {
        visible: true,
        message: activeMsg({'zh-TW':'資料已在其他地方更新。已載入最新版本；你的未儲存內容仍保留，請確認後再送出。','zh-CN':'数据已在其他地方更新。已加载最新版本；你的未保存内容仍保留，请确认后再次提交。',en:'This data was updated elsewhere. The latest version is loaded; your unsaved work was preserved. Review it and submit again.'}),
        ...draft,
      },
    };
  }
}
