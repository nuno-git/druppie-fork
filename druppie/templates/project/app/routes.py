"""API routes.

Define your API endpoints here. All routes are prefixed with /api.

Built-in AI endpoints (via Druppie SDK → module-llm):
    POST /api/ai/chat  — LLM chat completion  (body: {prompt, system?})
    POST /api/ai/ocr   — OCR text extraction   (body: {image_url})

Example adding your own:

    @api.route('/items', methods=['GET'])
    def list_items():
        db = next(get_db())
        items = db.query(Item).all()
        return jsonify([{'id': str(i.id), 'name': i.name} for i in items])
"""

from flask import Blueprint, jsonify, request
from druppie_sdk import DruppieClient

api = Blueprint("api", __name__)

druppie = DruppieClient()


@api.route("/info")
def info():
    from app.config import settings

    return jsonify(app_name=settings.app_name)


# ---------------------------------------------------------------------------
# AI endpoints — via Druppie SDK (calls module-llm on the platform)
# ---------------------------------------------------------------------------


@api.route("/ai/chat", methods=["POST"])
def ai_chat_endpoint():
    """LLM chat completion. Body: {"prompt": "...", "system": "..."}"""
    data = request.get_json(silent=True)
    if not data or "prompt" not in data:
        return jsonify(error="Missing required field: prompt"), 400
    result = druppie.call("llm", "chat", {
        "prompt": data["prompt"],
        "system": data.get("system", "You are a helpful assistant."),
    })
    return jsonify(answer=result.get("answer", ""))


@api.route("/ai/ocr", methods=["POST"])
def ai_ocr_endpoint():
    """OCR text extraction. Body: {"image_url": "https://..."}"""
    data = request.get_json(silent=True)
    if not data or "image_url" not in data:
        return jsonify(error="Missing required field: image_url"), 400
    result = druppie.call("llm", "vision", {"image_url": data["image_url"]})
    return jsonify(text=result.get("text", ""))
