"""Mock LLM provider — deterministic, no API key required."""
import json
import uuid
from typing import Optional

from .base import LLMProvider


class MockProvider(LLMProvider):
    """Deterministic mock provider for testing/development."""

    @property
    def name(self) -> str:
        return "mock"

    async def complete(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> str:
        """Return deterministic responses based on system prompt type."""
        system_lower = system.lower()

        # Detect which prompt template is being used
        if "expand" in system_lower and "子節點建議" in system:
            return self._expand_response(user)
        elif "深化" in system and "content_blocks" in system:
            return self._deepen_response()
        elif "專案顧問" in system or "對話" in system:
            return "這是 Mock 模式的回覆。在實際配置 API Key 後才能獲得真實 AI 回應。"
        elif "連線成功" in user:
            return "連線成功！Mock Provider 運作正常。"
        else:
            return json.dumps([
                {"title": "範例建議標題", "summary": "這是一個示範性的Summary內容", "node_type": "task"}
            ])

    def _expand_response(self, user_prompt: str) -> str:
        """Generate mock expand suggestions."""
        # Check user prompt for mode hints
        mode = "explore"
        if "focused" in user_prompt.lower():
            mode = "focused"
        elif "challenge" in user_prompt.lower():
            mode = "challenge"

        suggestions = [
            {
                "title": f"[{mode}] 概念驗證",
                "summary": "建立基本 PoC，驗證核心功能的可行性。重點在於快速迭代和學習。",
                "node_type": "task"
            },
            {
                "title": f"[{mode}] 技術調研",
                "summary": "調研相關技術堆疊，包含效能、擴展性和維護成本評估。需產出比較矩陣。",
                "node_type": "task"
            },
            {
                "title": f"[{mode}] 使用者訪談",
                "summary": "進行至少 5 位潛在使用者訪談，收集需求痛點和使用場景描述。",
                "node_type": "task"
            },
        ]
        return json.dumps(suggestions, ensure_ascii=False)

    def _deepen_response(self) -> str:
        """Generate mock deepen content."""
        result = {
            "enriched_summary": "這是一個經過 Mock Provider 深化的摘要。在實際配置 API Key 後，AI 會根據上下文產生更具體且相關的內容。",
            "content_blocks": [
                {
                    "title": "定義與範圍",
                    "body": "此模組的核心職責包括：(1) 資料處理、(2) 狀態管理、(3) 與其他模組的介面整合。需要明確界定邊界條件。",
                    "block_type": "definition"
                },
                {
                    "title": "實施規則",
                    "body": "1. 所有公開方法必須有對應的單元測試\n2. 必須遵循既定的命名規範\n3.重大變更需經 code review",
                    "block_type": "rules"
                },
                {
                    "title": "範例案例",
                    "body": "情境：使用者登入\n輸入 → 驗證憑證 → 调用認證服務 → 產生 session → 回傳成功\n這是最基本的流程示意。",
                    "block_type": "examples"
                },
            ]
        }
        return json.dumps(result, ensure_ascii=False) if hasattr(result, '__name__') else json.dumps(result, ensure_ascii=False)