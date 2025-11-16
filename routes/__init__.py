# routes/__init__.py
"""
Đăng ký tất cả các blueprints
"""


def register_blueprints(app):
    """Đăng ký tất cả các routes vào Flask app"""

    from .static_pages import static_bp
    from .audio import audio_bp
    from .embedding import embedding_bp
    from .interview_batch import batch_bp
    from .interview_process import interview_bp
    from .auth import auth_bp  # ← THÊM DÒNG NÀY
    from .administrator import admin_bp

    # Register blueprints
    app.register_blueprint(static_bp)
    app.register_blueprint(audio_bp, url_prefix='/audio')
    app.register_blueprint(embedding_bp, url_prefix='/embedding')
    app.register_blueprint(batch_bp, url_prefix='/interview_batch')
    app.register_blueprint(interview_bp, url_prefix='/interview')
    app.register_blueprint(auth_bp)  # ← THÊM DÒNG NÀY (không có prefix)
    app.register_blueprint(admin_bp, url_prefix='/admin')
    print("✅ Đã đăng ký tất cả blueprints")