#!/usr/bin/env python3
"""Investment Assistant web app."""

from __future__ import annotations

import functools
import hashlib
import json
import os
import sys
from datetime import datetime

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.environment import EnvironmentCollector
from core.interview import InterviewManager
from core.openai_client import OpenAIClient
from core.preference_learner import PreferenceLearner
from core.research import ResearchEngine
from core.storage import Storage


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "investment-assistant-local-dev")

storage = Storage()
client = None
interview_manager = None
env_collector = None
research_engine = None
preference_learner = None


def get_auth_config():
    config = storage.get_config()
    return {
        "enabled": config.get("auth_enabled", False),
        "password_hash": config.get("auth_password_hash"),
    }


def check_auth(password: str) -> bool:
    auth_config = get_auth_config()
    if not auth_config["enabled"] or not auth_config["password_hash"]:
        return True
    return hashlib.sha256(password.encode()).hexdigest() == auth_config["password_hash"]


def requires_auth(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_config = get_auth_config()
        if not auth_config["enabled"]:
            return f(*args, **kwargs)
        if session.get("authenticated"):
            return f(*args, **kwargs)
        auth = request.authorization
        if auth and check_auth(auth.password):
            session["authenticated"] = True
            return f(*args, **kwargs)
        return Response("需要登录才能访问 Investment Assistant", 401, {"WWW-Authenticate": 'Basic realm="Investment Assistant"'})

    return decorated


def get_client():
    global client, interview_manager, env_collector, research_engine, preference_learner
    if client is None:
        api_key = storage.get_api_key()
        if api_key:
            client = OpenAIClient(api_key)
            interview_manager = InterviewManager(client, storage)
            env_collector = EnvironmentCollector(client, storage)
            research_engine = ResearchEngine(client, storage)
            preference_learner = PreferenceLearner(client, storage)
    return client


@app.route("/")
@requires_auth
def index():
    portfolio = storage.get_portfolio_playbook()
    stocks = []
    for stock in storage.list_stocks():
        history = storage.get_recent_research(stock["stock_id"], limit=1)
        stock["last_research"] = history[0] if history else None
        stocks.append(stock)
    return render_template("index.html", portfolio=portfolio, stocks=stocks, model=os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"))


@app.route("/portfolio")
@requires_auth
def portfolio():
    return render_template("portfolio.html", playbook=storage.get_portfolio_playbook())


@app.route("/stocks")
@requires_auth
def stocks():
    return render_template("stocks.html", stocks=storage.list_stocks())


@app.route("/stock/<stock_id>")
@requires_auth
def stock_detail(stock_id):
    return render_template(
        "stock_detail.html",
        playbook=storage.get_stock_playbook(stock_id),
        history=storage.get_recent_research(stock_id, limit=10),
        stock_id=stock_id,
    )


@app.route("/add-stock")
@requires_auth
def add_stock():
    return render_template("add_stock.html")


@app.route("/research-history")
@requires_auth
def research_history():
    all_history = []
    for stock in storage.list_stocks():
        for item in storage.get_recent_research(stock["stock_id"], limit=20):
            item["stock_name"] = stock["stock_name"]
            item["stock_id"] = stock["stock_id"]
            all_history.append(item)
    all_history.sort(key=lambda x: x.get("date", ""), reverse=True)
    return render_template("research_history.html", history=all_history)


@app.route("/preferences")
@requires_auth
def preferences_page():
    return render_template(
        "preferences.html",
        preferences=storage.get_user_preferences(),
        interactions=storage.get_recent_interactions(20),
    )


@app.route("/batch-scan")
@requires_auth
def batch_scan_page():
    return render_template("batch_scan.html", stocks=storage.list_stocks())


@app.route("/logout")
def logout():
    session.pop("authenticated", None)
    return redirect(url_for("index"))


@app.route("/api/auth/setup", methods=["POST"])
def api_setup_auth():
    data = request.json or {}
    config = storage.get_config()
    password = data.get("password", "")
    enable = data.get("enable", True)
    if password:
        config["auth_password_hash"] = hashlib.sha256(password.encode()).hexdigest()
    config["auth_enabled"] = enable
    storage.save_config(config)
    return jsonify({"success": True, "auth_enabled": enable})


@app.route("/api/auth/status", methods=["GET"])
def api_auth_status():
    auth_config = get_auth_config()
    return jsonify({"enabled": auth_config["enabled"], "has_password": bool(auth_config["password_hash"])})


@app.route("/api/portfolio", methods=["GET"])
def api_get_portfolio():
    return jsonify(storage.get_portfolio_playbook() or {})


@app.route("/api/portfolio", methods=["POST"])
def api_save_portfolio():
    data = request.json or {}
    storage.save_portfolio_playbook(data)
    return jsonify({"success": True})


@app.route("/api/stock/<stock_id>", methods=["GET"])
def api_get_stock(stock_id):
    return jsonify(storage.get_stock_playbook(stock_id) or {})


@app.route("/api/stock/<stock_id>", methods=["POST"])
def api_save_stock(stock_id):
    data = request.json or {}
    data["stock_id"] = stock_id
    storage.save_stock_playbook(stock_id, data)
    return jsonify({"success": True})


@app.route("/api/stock/<stock_id>", methods=["DELETE"])
def api_delete_stock(stock_id):
    return jsonify({"success": storage.delete_stock(stock_id)})


@app.route("/api/interview/start", methods=["POST"])
def api_start_interview():
    get_client()
    if not interview_manager:
        return jsonify({"error": "API Key 未配置"}), 400
    data = request.json or {}
    interview_type = data.get("type", "stock")
    stock_name = data.get("stock_name", "")
    message = (
        interview_manager.start_portfolio_interview()
        if interview_type == "portfolio"
        else interview_manager.start_stock_interview(stock_name)
    )
    return jsonify({"message": message})


@app.route("/api/interview/continue", methods=["POST"])
def api_continue_interview():
    get_client()
    if not interview_manager:
        return jsonify({"error": "API Key 未配置"}), 400
    data = request.json or {}
    interview_type = data.get("type", "stock")
    stock_name = data.get("stock_name", "")
    user_input = data.get("message", "")
    if interview_type == "portfolio":
        response, playbook = interview_manager.continue_portfolio_interview(user_input)
    else:
        response, playbook = interview_manager.continue_stock_interview(user_input, stock_name)
    result = {"message": response, "completed": playbook is not None}
    if playbook:
        result["playbook"] = playbook
        if interview_type == "portfolio":
            storage.save_portfolio_playbook(playbook)
        else:
            stock_id = stock_name.lower().replace(" ", "_")
            storage.save_stock_playbook(stock_id, playbook)
    return jsonify(result)


@app.route("/api/research/<stock_id>/environment", methods=["POST"])
def api_collect_environment(stock_id):
    get_client()
    if not env_collector:
        return jsonify({"error": "API Key 未配置"}), 400
    days = int(request.form.get("days", 7))
    playbook = storage.get_stock_playbook(stock_id)
    stock_name = playbook.get("stock_name", stock_id) if playbook else stock_id
    news_result = env_collector.collect_news(stock_id, stock_name, days)
    uploaded = []
    if "files" in request.files:
        files = request.files.getlist("files")
        for file in files:
            if file.filename:
                temp_path = os.path.join(os.getenv("TEMP", "."), file.filename)
                file.save(temp_path)
                uploaded.append(env_collector.analyze_file(temp_path))
                if os.path.exists(temp_path):
                    os.remove(temp_path)
    return jsonify({"news": news_result["news"], "uploaded_files_analysis": uploaded, "search_metadata": news_result["search_metadata"]})


@app.route("/api/research/<stock_id>/assess", methods=["POST"])
def api_assess_impact(stock_id):
    get_client()
    if not env_collector:
        return jsonify({"error": "API Key 未配置"}), 400
    data = request.json or {}
    return jsonify(
        env_collector.assess_impact(
            stock_id=stock_id,
            time_range=data.get("time_range", "7d"),
            auto_collected=data.get("news", []),
            user_uploaded=data.get("uploaded_files", []),
        )
    )


@app.route("/api/research/<stock_id>/follow-up", methods=["POST"])
def api_follow_up_research(stock_id):
    get_client()
    if not client:
        return jsonify({"error": "API Key 未配置"}), 400
    data = request.json or {}
    report = data.get("research_report", "")
    question = data.get("question", "")
    answer = client.chat(f"请基于以下研究报告回答用户追问。\n\n报告:\n{report[:10000]}\n\n问题:\n{question}")
    return jsonify({"answer": answer})


@app.route("/api/research/<stock_id>/adjust-plan", methods=["POST"])
def api_adjust_plan(stock_id):
    get_client()
    if not client:
        return jsonify({"error": "API Key 未配置"}), 400
    data = request.json or {}
    current_plan = data.get("current_plan", {})
    adjustment = data.get("adjustment_request", "")
    answer = client.chat(
        "请基于当前研究计划和用户要求，输出更新后的 JSON。\n"
        f"当前计划:\n{json.dumps(current_plan, ensure_ascii=False, indent=2)}\n"
        f"调整要求:\n{adjustment}"
    )
    return jsonify({"adjustment_summary": adjustment, "updated_plan": current_plan, "raw_answer": answer})


@app.route("/api/research/<stock_id>/execute", methods=["POST"])
def api_execute_research(stock_id):
    get_client()
    if not research_engine:
        return jsonify({"error": "API Key 未配置"}), 400
    data = request.json or {}
    environment_data = {
        "time_range": data.get("time_range", "7d"),
        "auto_collected": data.get("news", []),
        "user_uploaded": [],
    }
    result = research_engine.execute_research(stock_id, data.get("research_plan", {}), environment_data)
    research_engine.save_research_record(stock_id, environment_data, data.get("assessment", {}), result)
    return jsonify(result)


@app.route("/api/research/<stock_id>/history", methods=["GET"])
def api_get_research_history(stock_id):
    return jsonify(storage.get_recent_research(stock_id, 20))


@app.route("/api/research/<stock_id>/feedback", methods=["POST"])
def api_save_research_feedback(stock_id):
    data = request.json or {}
    recent = storage.get_recent_research(stock_id, 1)
    if not recent:
        return jsonify({"error": "没有找到研究记录"}), 404
    success = storage.update_research_feedback(stock_id, recent[0]["id"], data.get("feedback", {}))
    return jsonify({"success": success, "record_id": recent[0]["id"]})


@app.route("/api/research/<stock_id>/context", methods=["GET"])
def api_get_research_context(stock_id):
    return jsonify(storage.get_research_context(stock_id, 3))


@app.route("/api/research/<stock_id>/milestone/<record_id>", methods=["POST"])
def api_toggle_milestone(stock_id, record_id):
    return jsonify({"success": True, "is_milestone": storage.toggle_milestone(stock_id, record_id)})


@app.route("/api/preferences", methods=["GET"])
def api_get_preferences():
    return jsonify(storage.get_user_preferences())


@app.route("/api/preferences", methods=["POST"])
def api_save_preferences():
    data = request.json or {}
    if "preference_summary" in data:
        storage.update_preference_summary(data["preference_summary"])
    return jsonify({"success": True})


@app.route("/api/preferences/add", methods=["POST"])
def api_add_preference():
    data = request.json or {}
    pref_id = storage.add_preference(
        {
            "trigger": data.get("trigger", ""),
            "my_response": data.get("my_response", ""),
            "category": data.get("category", "general"),
            "confidence": "高",
            "reasoning": "手动添加",
            "source": "manual",
        }
    )
    return jsonify({"success": True, "id": pref_id})


@app.route("/api/preferences/<pref_id>", methods=["PUT"])
def api_update_preference(pref_id):
    return jsonify({"success": storage.update_preference(pref_id, request.json or {})})


@app.route("/api/preferences/<pref_id>", methods=["DELETE"])
def api_delete_preference(pref_id):
    return jsonify({"success": storage.delete_preference(pref_id)})


@app.route("/api/preferences/<pref_id>/toggle", methods=["POST"])
def api_toggle_preference(pref_id):
    return jsonify({"success": storage.toggle_preference(pref_id)})


@app.route("/api/preferences/learn", methods=["POST"])
def api_learn_preferences():
    get_client()
    if not preference_learner:
        return jsonify({"error": "API Key 未配置"}), 400
    return jsonify(preference_learner.learn_and_save_preferences())


@app.route("/api/preferences/interactions", methods=["GET"])
def api_get_interactions():
    return jsonify(storage.get_recent_interactions(request.args.get("limit", 20, type=int)))


@app.route("/api/batch-scan/stock/<stock_id>", methods=["POST"])
def api_scan_single_stock(stock_id):
    get_client()
    if not env_collector:
        return jsonify({"error": "API Key 未配置"}), 400
    days = (request.json or {}).get("days", 7)
    playbook = storage.get_stock_playbook(stock_id)
    stock_name = playbook.get("stock_name", stock_id) if playbook else stock_id
    news_result = env_collector.collect_news(stock_id, stock_name, days)
    assessment = env_collector.assess_impact(stock_id, f"{days}天", news_result["news"], [])
    return jsonify(
        {
            "stock_id": stock_id,
            "stock_name": stock_name,
            "days": days,
            "news_count": len(news_result["news"]),
            "news": news_result["news"],
            "assessment": assessment,
            "needs_research": assessment.get("judgment", {}).get("needs_deep_research", False),
            "confidence": assessment.get("judgment", {}).get("confidence", ""),
            "urgency": assessment.get("judgment", {}).get("urgency", ""),
            "summary": assessment.get("conclusion", {}).get("summary", ""),
            "key_risk": assessment.get("conclusion", {}).get("key_risk", ""),
            "key_opportunity": assessment.get("conclusion", {}).get("key_opportunity", ""),
            "search_metadata": news_result["search_metadata"],
            "invalidation_warnings": [],
        }
    )


@app.route("/api/batch-scan/research/<stock_id>", methods=["POST"])
def api_batch_research_stock(stock_id):
    return api_execute_research(stock_id)


if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("Investment Assistant Web")
    print("=" * 50)
    print(f"\n访问地址: http://localhost:{os.getenv('PORT', '5000')}")
    print(f"模型: {os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview')}\n")
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
