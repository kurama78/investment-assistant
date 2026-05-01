"""Research execution."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Dict, Optional

from .openai_client import OpenAIClient
from .storage import Storage


class ResearchEngine:
    def __init__(self, client: OpenAIClient, storage: Storage):
        self.client = client
        self.storage = storage

    def execute_research(self, stock_id: str, research_plan: Dict, environment_data: Dict) -> Dict:
        portfolio = self.storage.get_portfolio_playbook()
        stock_playbook = self.storage.get_stock_playbook(stock_id)
        stock_name = stock_playbook.get("stock_name", stock_id) if stock_playbook else stock_id
        prompt = f"""
请基于以下信息生成一份结构清晰的深度研究报告，并在文末输出 JSON 结论。

股票: {stock_name}
组合 Playbook:
{json.dumps(portfolio or {{}}, ensure_ascii=False, indent=2)}

个股 Playbook:
{json.dumps(stock_playbook or {{}}, ensure_ascii=False, indent=2)}

研究计划:
{json.dumps(research_plan or {{}}, ensure_ascii=False, indent=2)}

环境变化:
{json.dumps(environment_data or {{}}, ensure_ascii=False, indent=2)}

文末 JSON 格式：
```json
{{
  "thesis_impact": "强化/削弱/动摇/无影响",
  "recommendation": "买入/增持/持有/减持/卖出",
  "confidence": "高/中/低",
  "position_suggestion": "",
  "key_finding": "",
  "reasoning": "",
  "key_risks": [],
  "key_catalysts": [],
  "follow_up_items": [],
  "next_research_trigger": []
}}
```
"""
        response = self.client.chat(prompt)
        conclusion = self._extract_conclusion(response)
        return {
            "full_report": response,
            "conclusion": conclusion,
            "key_findings": [conclusion.get("key_finding", "")] if conclusion.get("key_finding") else [],
            "search_results": "",
            "executed_at": datetime.now().isoformat(),
        }

    def _extract_conclusion(self, response: str) -> Dict:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        return {
            "thesis_impact": "待定",
            "recommendation": "持有",
            "confidence": "低",
            "position_suggestion": "",
            "key_finding": "结论 JSON 解析失败",
            "reasoning": "请查看完整报告原文。",
            "key_risks": [],
            "key_catalysts": [],
            "follow_up_items": [],
            "next_research_trigger": [],
        }

    def save_research_record(
        self,
        stock_id: str,
        environment_data: Dict,
        impact_assessment: Dict,
        research_result: Optional[Dict],
        user_feedback: Optional[Dict] = None,
    ):
        record = {
            "trigger": "user_initiated",
            "environment_input": environment_data,
            "impact_assessment": impact_assessment,
            "research_plan": impact_assessment.get("research_plan"),
            "research_result": research_result.get("conclusion") if research_result else None,
            "full_report": research_result.get("full_report") if research_result else None,
            "user_feedback": user_feedback,
        }
        self.storage.add_research_record(stock_id, record)
