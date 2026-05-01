"""Gemini client shim.

Kept as ``openai_client.py`` so the rest of the upstream code can run
without changing its imports while we use Gemini on both local and Render.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
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
            raise ValueError("Please set GEMINI_API_KEY in the environment or config.")

        self.client = genai.Client(api_key=self.api_key)
        self.model = model

    def _generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        config: Optional[types.GenerateContentConfig] = None,
    ) -> str:
        if config is None:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
            )
        elif system_prompt and getattr(config, "system_instruction", None) is None:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=getattr(config, "temperature", 0.2),
                tools=getattr(config, "tools", None),
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
            prompt = f"Conversation history:\n{transcript}\n\nCurrent task:\n{prompt}"
        return self._generate(prompt)

    def chat_with_system(
        self, system_prompt: str, user_message: str, history: Optional[List[Dict]] = None
    ) -> str:
        prompt = user_message
        if history:
            transcript = "\n".join(
                f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in history
            )
            prompt = f"Conversation history:\n{transcript}\n\nCurrent task:\n{user_message}"
        return self._generate(prompt, system_prompt=system_prompt)

    def search(self, query: str, time_range_days: int = 7) -> str:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=max(time_range_days - 1, 0))
        prompt = (
            "Use Google Search grounding to summarize the most important public updates "
            f"from {start_date.isoformat()} to {end_date.isoformat()}.\n"
            f"Topic: {query}\n"
            "If no reliable updates are available in this window, say that clearly."
        )
        config = types.GenerateContentConfig(
            temperature=0.1,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
        try:
            return self._generate(prompt, config=config)
        except Exception:
            return self._generate(
                (
                    "Summarize only if you are confident. "
                    f"Focus on the last {time_range_days} days for: {query}. "
                    "If you are not certain, explicitly say you are not certain."
                )
            )

    def search_news_structured(
        self,
        stock_name: str,
        related_entities: List[str],
        time_range_days: int = 7,
        playbook: Optional[Dict] = None,
    ) -> List[Dict]:
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=max(time_range_days - 1, 0))
        entities = ", ".join(related_entities[:8]) if related_entities else "None"
        playbook_summary = json.dumps(playbook or {}, ensure_ascii=False)[:1800]

        prompt = f"""
Return JSON only in this exact shape:
{{
  "news": [
    {{
      "date": "YYYY-MM-DD",
      "title": "headline",
      "summary": "brief summary",
      "dimension": "company_core_dynamics/industry_competition/product_technology/macro_policy",
      "relevance": "why it matters to the stock",
      "importance": "high/medium/low",
      "source": "source name",
      "url": "https://..."
    }}
  ]
}}

Use Google Search grounding and only include items that happened or were published from
{start_date.isoformat()} to {end_date.isoformat()} inclusive.

Target company: {stock_name}
Related entities: {entities}
Playbook summary: {playbook_summary}

Rules:
1. If you cannot verify a news item is inside this exact date window, do not include it.
2. Prefer exchange filings, company announcements, reputable financial media, and official sources.
3. If there are no reliable items in this date window, return {{"news": []}}.
4. Do not include commentary outside JSON.
"""

        grounded_config = types.GenerateContentConfig(
            temperature=0.1,
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        warnings: List[str] = []
        try:
            text = self._generate(prompt, config=grounded_config)
            source_label = "Source: Gemini Google Search grounding"
        except Exception as exc:
            warnings.append(f"Grounded search failed, fell back to model-only output: {exc}")
            text = self._generate(prompt)
            source_label = "Source: Gemini model output fallback"

        payload = self._extract_json_payload(text)
        if not payload:
            return [
                {
                    "_is_metadata": True,
                    "search_warnings": warnings
                    + [f"{source_label}; Gemini did not return parseable JSON."],
                }
            ]

        filtered_news = self._filter_news_items(
            payload.get("news", []),
            start_date=start_date,
            end_date=end_date,
        )

        if len(filtered_news) < len(payload.get("news", [])):
            warnings.append("Dropped items outside the requested date range or with invalid dates.")

        return [
            {
                "_is_metadata": True,
                "search_warnings": [source_label, *warnings],
            },
            *filtered_news,
        ]

    def _extract_json_payload(self, text: str) -> Optional[Dict]:
        match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", text)
        candidates = [match.group(1)] if match else []

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(text[start : end + 1])

        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        return None

    def _filter_news_items(
        self,
        news: List[Dict],
        *,
        start_date,
        end_date,
    ) -> List[Dict]:
        filtered: List[Dict] = []
        seen = set()

        for item in news:
            if not isinstance(item, dict):
                continue

            date_text = str(item.get("date", "")).strip()
            try:
                item_date = datetime.strptime(date_text, "%Y-%m-%d").date()
            except ValueError:
                continue

            if not (start_date <= item_date <= end_date):
                continue

            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            dedupe_key = (title.lower(), url.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            filtered.append(
                {
                    "date": date_text,
                    "title": title,
                    "summary": str(item.get("summary", "")).strip(),
                    "dimension": str(item.get("dimension", "")).strip(),
                    "relevance": str(item.get("relevance", "")).strip(),
                    "importance": str(item.get("importance", "")).strip(),
                    "source": str(item.get("source", "")).strip(),
                    "url": url,
                }
            )

        filtered.sort(key=lambda x: x.get("date", ""), reverse=True)
        return filtered

    def analyze_file(self, file_path: str, prompt: str) -> str:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md", ".json", ".csv"}:
            content = path.read_text(encoding="utf-8", errors="ignore")[:12000]
            return self._generate(f"{prompt}\n\nFile content:\n{content}")
        return self._generate(
            f"{prompt}\n\nFilename: {path.name}\nNote: only plain-text file content is supported."
        )

    @property
    def model_pro(self) -> str:
        return self.model

    @property
    def model_flash(self) -> str:
        return self.model
