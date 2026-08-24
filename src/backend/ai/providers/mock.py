"""Mock LLM provider — deterministic, localized, and network-free."""
import json
from typing import Optional
from .base import LLMProvider

_MODES = {"focused", "explore", "challenge"}
_EXPAND_KEYS = {
    "context", "mode_key", "mode", "requested_count",
    "existing_children", "existing_siblings", "instruction",
}


def _title_group(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"label", "titles"}
        and isinstance(value["label"], str)
        and isinstance(value["titles"], list)
        and all(isinstance(title, str) for title in value["titles"])
    )


def _instruction(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"label", "value"}
        and isinstance(value["label"], str)
        and (value["value"] is None or isinstance(value["value"], str))
    )


class MockProvider(LLMProvider):
    @property
    def name(self) -> str: return "mock"

    async def complete(self, system: str, user: str, model: Optional[str] = None, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        locale = "en" if "write all generated text in english" in system.lower() else "zh-CN" if "简体中文" in system else "zh-TW"
        payload = self._parse_payload(user)

        # Task selection requires both the current structured envelope and the
        # response contract. User-controlled strings never select task or mode.
        if self._deepen_payload(payload) and self._deepen_contract(system):
            return json.dumps(self._deepen(locale), ensure_ascii=False)
        expand = self._expand_payload(payload)
        if expand is not None and self._expand_contract(system):
            mode, count = expand
            return json.dumps(self._expand(locale, mode, count), ensure_ascii=False)

        replies={"en":"This is a Mock-mode response. Configure an API key to receive a live AI response.","zh-CN":"这是 Mock 模式的回复。配置 API Key 后即可获得真实 AI 回复。","zh-TW":"這是 Mock 模式的回覆。設定 API Key 後即可獲得真實 AI 回應。"}
        return replies[locale]

    @staticmethod
    def _parse_payload(user: str) -> Optional[dict]:
        try:
            payload = json.loads(user)
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _expand_contract(system: str) -> bool:
        lowered = system.lower()
        return "content_blocks" not in lowered and all(key in lowered for key in ("title", "summary", "node_type"))

    @staticmethod
    def _deepen_contract(system: str) -> bool:
        lowered = system.lower()
        return "enriched_summary" in lowered and "content_blocks" in lowered

    @staticmethod
    def _expand_payload(payload: Optional[dict]) -> Optional[tuple[str, int]]:
        """Validate the current envelope; invalid mode/type fails closed to generic."""
        if not isinstance(payload, dict) or set(payload) != _EXPAND_KEYS:
            return None
        mode = payload.get("mode_key")
        count = payload.get("requested_count")
        if (
            not isinstance(payload.get("context"), dict)
            or not isinstance(mode, str) or mode not in _MODES
            or not isinstance(payload.get("mode"), str)
            or not isinstance(count, int) or isinstance(count, bool)
            or not _title_group(payload.get("existing_children"))
            or not _title_group(payload.get("existing_siblings"))
            or not _instruction(payload.get("instruction"))
        ):
            return None
        return mode, max(1, min(8, count))

    @staticmethod
    def _deepen_payload(payload: Optional[dict]) -> bool:
        return (
            isinstance(payload, dict)
            and set(payload) == {"context", "instruction"}
            and isinstance(payload.get("context"), dict)
            and _instruction(payload.get("instruction"))
        )

    def _expand(self, locale: str, mode: str, count: int) -> list[dict]:
        rows={
          "en":[("Proof of concept","Build a minimal PoC that tests the core behavior and records pass/fail evidence."),("Technical evaluation","Compare performance, scalability, and maintenance cost in a decision matrix."),("User interviews","Interview at least five target users and document needs and scenarios.")],
          "zh-CN":[("概念验证","构建最小 PoC，验证核心行为并记录通过或失败的证据。"),("技术调研","通过决策矩阵比较性能、扩展性和维护成本。"),("用户访谈","访谈至少五位目标用户，并记录需求和使用场景。")],
          "zh-TW":[("概念驗證","建立最小 PoC，驗證核心行為並記錄通過或失敗的證據。"),("技術調研","透過決策矩陣比較效能、擴充性與維護成本。"),("使用者訪談","訪談至少五位目標使用者，並記錄需求與使用情境。")],
        }
        suggestions=[]
        for index in range(count):
            title, summary = rows[locale][index % len(rows[locale])]
            suffix = "" if index < len(rows[locale]) else f" {index + 1}"
            suggestions.append({"title":f"[{mode}] {title}{suffix}","summary":summary,"node_type":"task"})
        return suggestions

    def _deepen(self, locale: str) -> dict:
        values={
          "en":("A Mock Provider summary that demonstrates localized, structured output.",[("Definition and scope","Define responsibilities, interfaces, and explicit boundary conditions.","definition"),("Implementation rules","Every public method has a unit test; major changes require review.","rules")]),
          "zh-CN":("这是 Mock Provider 生成的本地化结构化摘要。",[("定义与范围","明确职责、接口和边界条件。","definition"),("实施规则","所有公开方法都要有单元测试；重大变更必须经过审查。","rules")]),
          "zh-TW":("這是 Mock Provider 產生的本地化結構化摘要。",[("定義與範圍","明確職責、介面與邊界條件。","definition"),("實作規則","所有公開方法都要有單元測試；重大變更必須經過審查。","rules")]),
        }
        summary,blocks=values[locale]
        return {"enriched_summary":summary,"content_blocks":[{"title":t,"body":b,"block_type":k} for t,b,k in blocks]}
