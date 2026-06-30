import os
import uuid
import json
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

from signals import llm_signal, stylo_signal
from scorer import combine_scores, generate_label
from audit import append_log, get_log, update_status

load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Rate limiting
# 10 per minute: a real writer submits occasionally, not dozens of times/min.
# 50 per day: generous for legitimate use; blocks scripted flooding.
# ---------------------------------------------------------------------------
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


# ---------------------------------------------------------------------------
# POST /submit
# ---------------------------------------------------------------------------
@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;50 per day")
def submit():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    text = data.get("text", "").strip()
    creator_id = data.get("creator_id", "").strip()

    if not text:
        return jsonify({"error": "Field 'text' is required and cannot be empty"}), 400
    if not creator_id:
        return jsonify({"error": "Field 'creator_id' is required"}), 400

    content_id = str(uuid.uuid4())

    # --- Signal 1: LLM ---
    llm_score, llm_reasoning = llm_signal(text)

    # --- Signal 2: Stylometrics ---
    stylo_score, stylo_detail = stylo_signal(text)

    # --- Confidence scoring ---
    confidence, attribution = combine_scores(llm_score, stylo_score, len(text.split()))

    # --- Transparency label ---
    label = generate_label(confidence)

    # --- Audit log ---
    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": round(confidence, 4),
        "llm_score": round(llm_score, 4),
        "stylo_score": round(stylo_score, 4),
        "stylo_detail": stylo_detail,
        "llm_reasoning": llm_reasoning,
        "status": "classified",
        "label": label,
        "text_preview": text[:200],
    }
    append_log(entry)

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": round(confidence, 4),
        "confidence_pct": f"{round(confidence * 100)}%",
        "llm_score": round(llm_score, 4),
        "stylo_score": round(stylo_score, 4),
        "label": label,
        "status": "classified",
    }), 200


# ---------------------------------------------------------------------------
# POST /appeal
# ---------------------------------------------------------------------------
@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    content_id = data.get("content_id", "").strip()
    creator_reasoning = data.get("creator_reasoning", "").strip()

    if not content_id:
        return jsonify({"error": "Field 'content_id' is required"}), 400
    if not creator_reasoning:
        return jsonify({"error": "Field 'creator_reasoning' is required"}), 400

    updated = update_status(content_id, "under_review", creator_reasoning)
    if not updated:
        return jsonify({"error": f"No submission found with content_id '{content_id}'"}), 404

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Your appeal has been received and will be reviewed by a human moderator.",
        "appeal_reasoning": creator_reasoning,
    }), 200


# ---------------------------------------------------------------------------
# GET /log
# ---------------------------------------------------------------------------
@app.route("/log", methods=["GET"])
def log():
    limit = request.args.get("limit", 20, type=int)
    entries = get_log(limit)
    return jsonify({"count": len(entries), "entries": entries}), 200


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Rate limit error handler
# ---------------------------------------------------------------------------
@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        "error": "Rate limit exceeded",
        "message": "You've submitted too many requests. Please wait before trying again.",
        "retry_after": str(e.description),
    }), 429


if __name__ == "__main__":
    app.run(debug=True)
