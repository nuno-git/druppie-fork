"""API routes.

Define your API endpoints here. All routes are prefixed with /api.

Example:

    @api.route('/items', methods=['GET'])
    def list_items():
        db = next(get_db())
        items = db.query(Item).all()
        return jsonify([{'id': str(i.id), 'name': i.name} for i in items])
"""

from flask import Blueprint, jsonify

api = Blueprint("api", __name__)


@api.route("/info")
def info():
    from app.config import settings

    return jsonify(app_name=settings.app_name)
