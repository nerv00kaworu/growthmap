"""Mock LLM provider — deterministic, localized, and network-free."""
import json
from typing import Optional
from .base import LLMProvider

class MockProvider(LLMProvider):
    @property
    def name(self) -> str: return "mock"

    async def complete(self, system: str, user: str, model: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        locale = "en" if "write all generated text in english" in system.lower() else "zh-CN" if "简体中文" in system else "zh-TW"
        if "content_blocks" in system:
            return json.dumps(self._deepen(locale), ensure_ascii=False)
        if "suggest" in system.lower() or "子節點" in system or "子节点" in system:
            payload = json.loads(user)
            mode = payload.get("mode_key", "explore")
            if mode not in {"focused", "explore", "challenge"}:
                mode = "explore"
            count = max(1, min(8, int(payload.get("requested_count", 3))))
            return json.dumps(self._expand(locale, mode)[:count], ensure_ascii=False)
        replies={"en":"This is a Mock-mode response. Configure an API key to receive a live AI response.","zh-CN":"这是 Mock 模式的回复。配置 API Key 后即可获得真实 AI 回复。","zh-TW":"這是 Mock 模式的回覆。設定 API Key 後即可獲得真實 AI 回應。"}
        return replies[locale]

    def _expand(self, locale: str, mode: str) -> list[dict]:
        rows={
          "en":[("Proof of concept","Build a minimal PoC that tests the core behavior and records pass/fail evidence."),("Technical evaluation","Compare performance, scalability, and maintenance cost in a decision matrix."),("User interviews","Interview at least five target users and document needs and scenarios.")],
          "zh-CN":[("概念验证","构建最小 PoC，验证核心行为并记录通过或失败的证据。"),("技术调研","通过决策矩阵比较性能、扩展性和维护成本。"),("用户访谈","访谈至少五位目标用户，并记录需求和使用场景。")],
          "zh-TW":[("概念驗證","建立最小 PoC，驗證核心行為並記錄通過或失敗的證據。"),("技術調研","透過決策矩陣比較效能、擴充性與維護成本。"),("使用者訪談","訪談至少五位目標使用者，並記錄需求與使用情境。")],
        }
        return [{"title":f"[{mode}] {title}","summary":summary,"node_type":"task"} for title,summary in rows[locale]]

    def _deepen(self, locale: str) -> dict:
        values={
          "en":("A Mock Provider summary that demonstrates localized, structured output.",[("Definition and scope","Define responsibilities, interfaces, and explicit boundary conditions.","definition"),("Implementation rules","Every public method has a unit test; major changes require review.","rules")]),
          "zh-CN":("这是 Mock Provider 生成的本地化结构化摘要。",[("定义与范围","明确职责、接口和边界条件。","definition"),("实施规则","所有公开方法都要有单元测试；重大变更必须经过审查。","rules")]),
          "zh-TW":("這是 Mock Provider 產生的本地化結構化摘要。",[("定義與範圍","明確職責、介面與邊界條件。","definition"),("實作規則","所有公開方法都要有單元測試；重大變更必須經過審查。","rules")]),
        }
        summary,blocks=values[locale]
        return {"enriched_summary":summary,"content_blocks":[{"title":t,"body":b,"block_type":k} for t,b,k in blocks]}
