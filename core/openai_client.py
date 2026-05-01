"""Gemini client shim.

Kept as ``openai_client.py`` to stay compatible with the original imports.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from google import genai
from google.genai import types


DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")


class OpenAIClient:
    """Compatibility wrapper around the Gemini API."""

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("请设置 GEMINI_API_KEY 环境变量或在 config.json 中配置 gemini_api_key")

        self.client = genai.Client(api_key=self.api_key)
        self.model = model

    def _generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.2,
        )
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return response.text or ""

    def chat(self, prompt: str, history: Optional[List[Dict]] = None) -> str:
        if history:
            transcript = "\n".join(
                f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in history
            )
            prompt = f"对话历史:\n{transcript}\n\n当前任务:\n{prompt}"
        return self._generate(prompt)

    def chat_with_system(
        self, system_prompt: str, user_message: str, history: Optional[List[Dict]] = None
    ) -> str:
        prompt = user_message
        if history:
            transcript = "\n".join(
                f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in history
            )
            prompt = f"对话历史:\n{transcript}\n\n当前任务:\n{user_message}"
        return self._generate(prompt, system_prompt=system_prompt)

    def search(self, query: str, time_range_days: int = 7) -> str:
        return self._generate(
            f"请基于你已知信息，概括过去约 {time_range_days} 天与以下主题相关的重要公开动态：{query}。"
            "如无法确认具体新闻，请明确说明不确定性。"
        )

    def search_news_structured(
        self,
        stock_name: str,
        related_entities: List[str],
        time_range_days: int = 7,
        playbook: Optional[Dict] = None,
    ) -> List[Dict]:
        entities = ", ".join(related_entities[:5]) if related_entities else "无"
        playbook_summary = json.dumps(playbook or {}, ensure_ascii=False)[:1500]
        prompt = f"""
请输出 JSON：
{{
  "news": [
    {{
      "date": "YYYY-MM-DD",
      "title": "标题",
      "summary": "摘要",
      "dimension": "公司核心动态/行业与竞争/产品与技术/宏观与政策",
      "relevance": "为什么相关",
      "importance": "高/中/低",
      "source": "来源名称",
      "url": ""
    }}
  ]
}}

目标公司: {stock_name}
相关实体: {entities}
时间范围: 过去 {time_range_days} 天
Playbook 摘要: {playbook_summary}

如果你无法可靠确认近期新闻，请返回空数组。
"""
        text = self._generate(prompt)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return [{"_is_metadata": True, "search_warnings": ["Gemini 未返回可解析 JSON"]}]
        try:
            payload = json.loads(text[start : end + 1])
            news = payload.get("news", [])
            return [
                {"_is_metadata": True, "search_warnings": ["来源: Gemini structured output"]},
                *news,
            ]
        except json.JSONDecodeError:
            return [{"_is_metadata": True, "search_warnings": ["Gemini JSON 解析失败"]}]

    def analyze_file(self, file_path: str, prompt: str) -> str:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".json", ".csv"}:
            content = path.read_text(encoding="utf-8", errors="ignore")[:12000]
            return self._generate(f"{prompt}\n\n文件内容:\n{content}")
        return self._generate(f"{prompt}\n\n文件名: {path.name}\n注意：当前仅能读取纯文本文件内容。")

    @property
    def model_pro(self) -> str:
        return self.model

    @property
    def model_flash(self) -> str:
        return self.model
