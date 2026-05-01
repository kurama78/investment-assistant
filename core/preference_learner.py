"""Preference learner."""

from __future__ import annotations

from typing import Dict

from .openai_client import OpenAIClient
from .storage import Storage


class PreferenceLearner:
    def __init__(self, client: OpenAIClient, storage: Storage):
        self.client = client
        self.storage = storage

    def log_feedback_interaction(self, stock_id: str, stock_name: str, context: Dict, feedback: Dict):
        self.storage.log_interaction(
            {
                "type": "research_feedback",
                "stock_id": stock_id,
                "stock_name": stock_name,
                "context": context,
                "user_feedback": feedback,
            }
        )

    def learn_and_save_preferences(self) -> Dict:
        interactions = self.storage.get_recent_interactions(20)
        summary = {"interaction_count": len(interactions)}
        self.storage.update_preference_summary(summary)
        return {"extracted_preferences": [], "preference_summary": summary}
