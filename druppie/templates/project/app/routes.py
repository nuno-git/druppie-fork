"""API routes.

Define your API endpoints here. All routes are prefixed with /api.

Built-in AI endpoints:
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

api = Blueprint("api", __name__)


@api.route("/info")
def info():
    from app.config import settings

    return jsonify(app_name=settings.app_name)


# ---------------------------------------------------------------------------
# AI endpoints — proxy to DeepInfra (key stays server-side)
# ---------------------------------------------------------------------------


@api.route("/ai/chat", methods=["POST"])
def ai_chat_endpoint():
    """LLM chat completion. Body: {"prompt": "...", "system": "..."}"""
    from app.ai import ai_chat

    data = request.get_json()
    answer = ai_chat(data["prompt"], data.get("system", "You are a helpful assistant."))
    return jsonify(answer=answer)


@api.route("/ai/ocr", methods=["POST"])
def ai_ocr_endpoint():
    """OCR text extraction. Body: {"image_url": "https://..."}"""
    from app.ai import ocr_extract

    data = request.get_json()
    text = ocr_extract(data["image_url"])
    return jsonify(text=text)
