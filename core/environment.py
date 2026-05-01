"""Environment collection."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .openai_client import OpenAIClient
from .storage import Storage


class EnvironmentCollector:
    def __init__(self, client: OpenAIClient, storage: Storage):
        self.client = client
        self.storage = storage

    def collect_news(self, stock_id: str, stock_name: str, time_range_days: int = 7) -> Dict:
        playbook = self.storage.get_stock_playbook(stock_id)
        related_entities = playbook.get("related_entities", []) if playbook else []
        raw = self.client.search_news_structured(stock_name, related_entities, time_range_days, playbook)
        metadata = {"search_warnings": []}
        news = []
        for item in raw:
            if isinstance(item, dict) and item.get("_is_metadata"):
                metadata = item
            elif isinstance(item, dict):
                news.append(item)
        return {"news": news, "search_metadata": metadata}

    def analyze_file(self, file_path: str) -> Dict:
        summary = self.client.analyze_file(
            file_path,
            "请用 4 个要点总结这份资料里与投资判断最相关的信息，并指出任何关键数字。",
        )
        return {
            "filename": file_path.replace("\\", "/").split("/")[-1],
            "summary": summary,
            "analyzed_at": datetime.now().isoformat(),
        }

    def assess_impact(
        self, stock_id: str, time_range: str, auto_collected: List[Dict], user_uploaded: List[Dict]
    ) -> Dict:
        portfolio = self.storage.get_portfolio_playbook()
        stock_playbook = self.storage.get_stock_playbook(stock_id)
        prompt = f"""
请输出 JSON，判断这些变化是否值得做深度研究。

组合 Playbook:
{json.dumps(portfolio or {{}}, ensure_ascii=False, indent=2)}

个股 Playbook:
{json.dumps(stock_playbook or {{}}, ensure_ascii=False, indent=2)}

新闻:
{json.dumps(auto_collected, ensure_ascii=False, indent=2)}

上传资料摘要:
{json.dumps(user_uploaded, ensure_ascii=False, indent=2)}

格式：
```json
{{
  "judgment": {{
    "needs_deep_research": true,
    "confidence": "高/中/低",
    "urgency": "立即/本周内/可观察"
  }},
  "dimension_analysis": {{
    "thesis_impact": {{
      "core_thesis_status": "强化/削弱/动摇/无影响",
      "invalidation_check": {{
        "any_triggered": false,
        "details": null
      }}
    }}
  }},
  "conclusion": {{
    "summary": "",
    "key_risk": "",
    "key_opportunity": ""
  }},
  "research_plan": {{
    "research_objective": "",
    "hypothesis_to_test": [],
    "research_modules": [],
    "key_metrics_to_track": [],
    "scenario_analysis": {{}},
    "decision_framework": {{}},
    "timeline": "",
    "priority_ranking": []
  }}
}}
```
"""
        response = self.client.chat(prompt)
        data, error = self._extract_json(response)
        if data:
            data["_raw_response"] = response
            return data
        return {
            "judgment": {"needs_deep_research": True, "confidence": "中", "urgency": "本周内"},
            "dimension_analysis": {"thesis_impact": {"core_thesis_status": "待定", "invalidation_check": {"any_triggered": False, "details": error}}},
            "conclusion": {"summary": "Gemini 返回结果无法解析，建议人工复核。", "key_risk": error or "", "key_opportunity": ""},
            "research_plan": {"research_objective": "核查当前变化对原有投资逻辑的影响", "research_modules": [], "priority_ranking": []},
            "_raw_response": response,
        }

    def _extract_json(self, response: str) -> Tuple[Optional[Dict], Optional[str]]:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        chunks = [match.group(1)] if match else []
        start = response.find("{")
        end = response.rfind("}")
        if start != -1 and end != -1:
            chunks.append(response[start : end + 1])
        for chunk in chunks:
            try:
                return json.loads(chunk), None
            except json.JSONDecodeError as exc:
                err = str(exc)
        return None, err if "err" in locals() else "未找到可解析 JSON"
