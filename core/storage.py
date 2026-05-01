"""Storage helpers."""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class Storage:
    def __init__(self, base_dir: Optional[str] = None):
        default_base_dir = Path(__file__).resolve().parents[1] / ".localdata"
        self.base_dir = Path(
            base_dir
            or os.getenv("INVESTMENT_ASSISTANT_DATA_DIR")
            or default_base_dir
        )
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "stocks").mkdir(exist_ok=True)
        (self.base_dir / "logs").mkdir(exist_ok=True)
        self.config_path = self.base_dir / "config.json"
        self.portfolio_playbook_path = self.base_dir / "portfolio_playbook.json"

    def get_config(self) -> Dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        return {}

    def save_config(self, config: Dict):
        self.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_api_key(self) -> Optional[str]:
        config = self.get_config()
        return config.get("gemini_api_key") or os.getenv("GEMINI_API_KEY")

    def set_api_key(self, api_key: str):
        config = self.get_config()
        config["gemini_api_key"] = api_key
        self.save_config(config)

    def get_portfolio_playbook(self) -> Optional[Dict]:
        if self.portfolio_playbook_path.exists():
            return json.loads(self.portfolio_playbook_path.read_text(encoding="utf-8"))
        return None

    def save_portfolio_playbook(self, playbook: Dict):
        playbook["updated_at"] = datetime.now().isoformat()
        playbook.setdefault("created_at", playbook["updated_at"])
        self.portfolio_playbook_path.write_text(
            json.dumps(playbook, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def has_portfolio_playbook(self) -> bool:
        return self.portfolio_playbook_path.exists()

    def _get_stock_dir(self, stock_id: str) -> Path:
        stock_dir = self.base_dir / "stocks" / stock_id.lower().replace(" ", "_")
        stock_dir.mkdir(parents=True, exist_ok=True)
        (stock_dir / "uploads").mkdir(exist_ok=True)
        return stock_dir

    def get_stock_playbook(self, stock_id: str) -> Optional[Dict]:
        path = self._get_stock_dir(stock_id) / "playbook.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def save_stock_playbook(self, stock_id: str, playbook: Dict):
        playbook["stock_id"] = stock_id
        playbook["updated_at"] = datetime.now().isoformat()
        playbook.setdefault("created_at", playbook["updated_at"])
        path = self._get_stock_dir(stock_id) / "playbook.json"
        path.write_text(json.dumps(playbook, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_stocks(self) -> List[Dict]:
        items = []
        for stock_dir in (self.base_dir / "stocks").iterdir() if (self.base_dir / "stocks").exists() else []:
            if stock_dir.is_dir():
                playbook = self.get_stock_playbook(stock_dir.name)
                if playbook:
                    items.append(
                        {
                            "stock_id": stock_dir.name,
                            "stock_name": playbook.get("stock_name", stock_dir.name),
                            "ticker": playbook.get("ticker", ""),
                            "summary": playbook.get("core_thesis", {}).get("summary", ""),
                            "updated_at": playbook.get("updated_at", ""),
                        }
                    )
        return items

    def delete_stock(self, stock_id: str) -> bool:
        stock_dir = self.base_dir / "stocks" / stock_id.lower().replace(" ", "_")
        if stock_dir.exists():
            shutil.rmtree(stock_dir)
            return True
        return False

    def get_research_history(self, stock_id: str) -> Dict:
        path = self._get_stock_dir(stock_id) / "history.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"stock_id": stock_id, "records": []}

    def add_research_record(self, stock_id: str, record: Dict):
        history = self.get_research_history(stock_id)
        record["id"] = f"research_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        record["date"] = datetime.now().isoformat()
        history["records"].insert(0, record)
        path = self._get_stock_dir(stock_id) / "history.json"
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_recent_research(self, stock_id: str, limit: int = 3) -> List[Dict]:
        return self.get_research_history(stock_id).get("records", [])[:limit]

    def update_research_feedback(self, stock_id: str, record_id: str, feedback: Dict) -> bool:
        history = self.get_research_history(stock_id)
        for record in history.get("records", []):
            if record.get("id") == record_id:
                record["user_feedback"] = feedback
                path = self._get_stock_dir(stock_id) / "history.json"
                path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
                return True
        return False

    def get_research_context(self, stock_id: str, limit: int = 3) -> List[Dict]:
        return self.get_recent_research(stock_id, limit)

    def toggle_milestone(self, stock_id: str, record_id: str) -> bool:
        history = self.get_research_history(stock_id)
        for record in history.get("records", []):
            if record.get("id") == record_id:
                record["is_milestone"] = not record.get("is_milestone", False)
                path = self._get_stock_dir(stock_id) / "history.json"
                path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
                return record["is_milestone"]
        return False

    def save_uploaded_file(self, stock_id: str, source_path: str) -> str:
        source = Path(source_path).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"文件不存在: {source_path}")
        dest = self._get_stock_dir(stock_id) / "uploads" / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{source.name}"
        shutil.copy2(source, dest)
        return str(dest)

    def get_historical_uploads(self, stock_id: str, limit: int = 5) -> List[Dict]:
        uploads_dir = self._get_stock_dir(stock_id) / "uploads"
        files = sorted(uploads_dir.glob("*"), reverse=True)[:limit]
        return [{"date": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d"), "filename": f.name, "summary": ""} for f in files]

    def _get_preferences_path(self) -> Path:
        return self.base_dir / "user_preferences.json"

    def get_user_preferences(self) -> Dict:
        path = self._get_preferences_path()
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"preferences": [], "preference_summary": {}, "interaction_log": []}

    def save_user_preferences(self, prefs: Dict):
        prefs["updated_at"] = datetime.now().isoformat()
        self._get_preferences_path().write_text(json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_preference(self, preference: Dict) -> str:
        prefs = self.get_user_preferences()
        pref_id = f"pref_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        preference["id"] = pref_id
        preference.setdefault("active", True)
        prefs["preferences"].insert(0, preference)
        self.save_user_preferences(prefs)
        return pref_id

    def update_preference(self, pref_id: str, updates: Dict) -> bool:
        prefs = self.get_user_preferences()
        for pref in prefs["preferences"]:
            if pref["id"] == pref_id:
                pref.update(updates)
                self.save_user_preferences(prefs)
                return True
        return False

    def delete_preference(self, pref_id: str) -> bool:
        prefs = self.get_user_preferences()
        original = len(prefs["preferences"])
        prefs["preferences"] = [p for p in prefs["preferences"] if p["id"] != pref_id]
        if len(prefs["preferences"]) != original:
            self.save_user_preferences(prefs)
            return True
        return False

    def toggle_preference(self, pref_id: str) -> bool:
        prefs = self.get_user_preferences()
        for pref in prefs["preferences"]:
            if pref["id"] == pref_id:
                pref["active"] = not pref.get("active", True)
                self.save_user_preferences(prefs)
                return True
        return False

    def get_active_preferences(self) -> List[Dict]:
        return [p for p in self.get_user_preferences().get("preferences", []) if p.get("active", True)]

    def update_preference_summary(self, summary: Dict):
        prefs = self.get_user_preferences()
        prefs["preference_summary"] = summary
        self.save_user_preferences(prefs)

    def log_interaction(self, interaction: Dict):
        prefs = self.get_user_preferences()
        interaction["timestamp"] = datetime.now().isoformat()
        prefs.setdefault("interaction_log", []).insert(0, interaction)
        prefs["interaction_log"] = prefs["interaction_log"][:100]
        self.save_user_preferences(prefs)

    def get_recent_interactions(self, limit: int = 20) -> List[Dict]:
        return self.get_user_preferences().get("interaction_log", [])[:limit]

    def get_preferences_for_prompt(self) -> str:
        prefs = self.get_user_preferences()
        return json.dumps(prefs.get("preference_summary", {}), ensure_ascii=False, indent=2)

    def log(self, message: str, level: str = "INFO"):
        path = self.base_dir / "logs" / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] [{level}] {message}\n")
