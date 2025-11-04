# routes/static_pages.py
"""
Routes cho các trang tĩnh (home, templates)
"""

from flask import Blueprint, render_template, request, session
from utils import clean_old_audio_files

static_bp = Blueprint('static', __name__)

@static_bp.context_processor
def inject_base_path():
    """Inject base_path vào tất cả templates"""
    return dict(base_path='/iview1' if 'fit.neu.edu.vn' in request.host else '')

@static_bp.route("/")
def index():
    clean_old_audio_files()
    return render_template("home.html")

@static_bp.route("/interview_batch")
@static_bp.route("/interview_batch/")
def interview_batch_page():
    # ✅ Kiểm tra đăng nhập (placeholder - sẽ implement đầy đủ sau)
    if not session.get('user'):
        return render_template("login.html")
    return render_template("interview_batch.html")

@static_bp.route("/interview_batch/detail/<batch_id>")
def interview_batch_detail_page(batch_id):
    if not session.get('user'):
        return render_template("login.html")
    return render_template("interview_batch_detail.html", session_id=batch_id)

@static_bp.route("/embedding")
def embedding_page():
    if not session.get('user'):
        return render_template("login.html")
    return render_template("embedding.html")

@static_bp.route("/embedding/detail/<vectorstore_id>")
def embedding_detail_page(vectorstore_id):
    if not session.get('user'):
        return render_template("login.html")
    return render_template("embedding_detail.html", vectorstore_id=vectorstore_id)

# ✅ Placeholder routes cho auth (sẽ move sang auth blueprint sau)
@static_bp.route("/login")
def login_page():
    return render_template("login.html")

@static_bp.route("/logout")
def logout():
    session.clear()
    return render_template("home.html")