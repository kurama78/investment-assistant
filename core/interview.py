"""Interview helpers."""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from .openai_client import OpenAIClient
from .storage import Storage


class InterviewManager:
    def __init__(self, client: OpenAIClient, storage: Storage):
        self.client = client
        self.storage = storage
        self.conversation_history: List[Dict] = []

    def reset(self):
        self.conversation_history = []

    def _format_history(self) -> str:
        if not self.conversation_history:
            return "（暂无）"
        return "\n".join(f"{m['role']}: {m['content']}" for m in self.conversation_history)

    def _extract_json(self, response: str) -> Optional[Dict]:
        matches = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        for chunk in reversed(matches):
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                pass
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(response[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None

    def start_portfolio_interview(self) -> str:
        self.reset()
        question = "你当前最看好的投资方向或主题是什么？"
        self.conversation_history.append({"role": "assistant", "content": question})
        return question

    def continue_portfolio_interview(self, user_input: str) -> Tuple[str, Optional[Dict]]:
        self.conversation_history.append({"role": "user", "content": user_input})
        prompt = f"""
你是投资教练。基于下面对话，继续追问；如果信息已经足够，就输出 JSON。

对话历史:
{self._format_history()}

如果输出 JSON，请严格使用：
```json
{{
  "market_views": {{
    "bullish_themes": [],
    "bearish_themes": [],
    "macro_views": []
  }},
  "portfolio_strategy": {{
    "target_allocation": {{}},
    "risk_tolerance": "",
    "holding_period": ""
  }},
  "watchlist": []
}}
```
"""
        response = self.client.chat(prompt)
        playbook = self._extract_json(response)
        if playbook:
            playbook["interview_transcript"] = self.conversation_history.copy()
            return response, playbook
        self.conversation_history.append({"role": "assistant", "content": response})
        return response, None

    def start_stock_interview(self, stock_name: str) -> str:
        self.reset()
        question = f"你为什么想研究或买入 {stock_name}？核心逻辑是什么？"
        self.conversation_history.append({"role": "assistant", "content": question})
        return question

    def continue_stock_interview(self, user_input: str, stock_name: str) -> Tuple[str, Optional[Dict]]:
        self.conversation_history.append({"role": "user", "content": user_input})
        portfolio = self.storage.get_portfolio_playbook()
        prompt = f"""
你是投资教练。请基于对话继续追问；如果信息足够，就输出个股 Playbook JSON。

股票: {stock_name}
组合 Playbook:
{json.dumps(portfolio or {{}}, ensure_ascii=False, indent=2)}

对话历史:
{self._format_history()}

JSON 格式：
```json
{{
  "stock_name": "{stock_name}",
  "ticker": "",
  "core_thesis": {{
    "summary": "",
    "key_points": [],
    "market_gap": ""
  }},
  "validation_signals": [],
  "invalidation_triggers": [],
  "operation_plan": {{
    "holding_period": "",
    "target_price": null,
    "stop_loss": null,
    "position_size": ""
  }},
  "related_entities": []
}}
```
"""
        response = self.client.chat(prompt)
        playbook = self._extract_json(response)
        if playbook:
            playbook.setdefault("stock_name", stock_name)
            playbook["interview_transcript"] = self.conversation_history.copy()
            return response, playbook
        self.conversation_history.append({"role": "assistant", "content": response})
        return response, None

    def start_update_portfolio_interview(self, current_playbook: Dict) -> str:
        self.reset()
        question = "你想更新组合层面的哪一部分观点？"
        self.conversation_history.append({"role": "assistant", "content": question})
        return question

    def start_update_stock_interview(self, stock_name: str, current_playbook: Dict) -> str:
        self.reset()
        summary = current_playbook.get("core_thesis", {}).get("summary", "")
        question = f"{stock_name} 当前核心逻辑是“{summary}”。你想修改哪部分？"
        self.conversation_history.append({"role": "assistant", "content": question})
        return question
