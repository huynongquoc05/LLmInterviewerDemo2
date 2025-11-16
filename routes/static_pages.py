# routes/static_pages.py
"""
Routes cho các trang tĩnh (home, templates)
"""

from flask import Blueprint, render_template, request, session, flash, redirect, url_for
from utils import clean_old_audio_files
from bson import ObjectId, errors  # <-- THÊM IMPORT
from extensions import db_vectorstores # <-- THÊM IMPORT
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
    # 1. Kiểm tra đăng nhập
    if not session.get('user'):
        flash("Vui lòng đăng nhập để tiếp tục", "warning")
        return redirect(url_for('auth.login_page'))

    user_id = session['user'].get('id')
    user_role = session['user'].get('role')

    try:
        # 2. Lấy thông tin Vectorstore
        vs = db_vectorstores.find_one({"_id": ObjectId(vectorstore_id)})
        if not vs:
            flash("Không tìm thấy tài liệu này", "danger")
            return redirect(url_for('embedding_page'))

        # 3. Kiểm tra quyền truy cập
        vs_owner_id = vs.get('user_id') or vs.get('custom', {}).get('user_id')

        # Cho phép truy cập nếu:
        # 1. User là Admin
        # 2. User là chủ sở hữu tài liệu
        # 3. Tài liệu là Public (user_id là None)
        if (user_role == 'admin' or
                vs_owner_id == user_id or
                vs_owner_id is None):
            return render_template("embedding_detail.html", vectorstore_id=vectorstore_id)

        # 4. Nếu không có quyền
        flash("Bạn không có quyền xem tài liệu này", "danger")
        return redirect(url_for('embedding_page'))

    except errors.InvalidId:
        flash("ID tài liệu không hợp lệ", "danger")
        return redirect(url_for('embedding_page'))
    except Exception as e:
        flash(f"Lỗi: {e}", "danger")
        return redirect(url_for('embedding_page'))


# ✅ Placeholder routes cho auth (sẽ move sang auth blueprint sau)
@static_bp.route("/login")
def login_page():
    return render_template("login.html")

@static_bp.route("/logout")
def logout():
    session.clear()
    return render_template("home.html")