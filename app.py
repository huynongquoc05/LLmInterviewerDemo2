# app.py (tiếp theo)
"""
File khởi động chính
"""

import threading
import time
from datetime import datetime
from flask import Flask, send_from_directory, request

from config import Config
from extensions import audio_cache, migrate_batches_add_user_id
from utils import clean_old_audio_files, cleanup_temp_files
from routes import register_blueprints
from database import init_db  # ← THÊM DÒNG NÀY

# ===================================================================
# Khởi tạo Flask App
# ===================================================================
app = Flask(__name__, static_url_path='/iview1/static', static_folder='static')
app.config.from_object(Config)
@app.context_processor
def inject_base_path(): return dict(base_path='/iview1' if 'fit.neu.edu.vn' in request.host else '')
# ✅ QUAN TRỌNG: Secret key cho session
app.secret_key = Config.SECRET_KEY  # Thêm vào config.py

# Tạo các thư mục cần thiết
Config.init_folders()

# ✅ QUAN TRỌNG: Khởi tạo database
init_db()

# ===================================================================
# Đăng ký Blueprints
# ===================================================================
register_blueprints(app)


# ===================================================================
# Background Cleanup Scheduler
# ===================================================================
def cleanup_scheduler():
    """Background task để dọn dẹp cache và file tạm"""
    while True:
        time.sleep(Config.AUDIO_CLEANUP_INTERVAL)

        # Xóa file audio cũ
        clean_old_audio_files()

        # Xóa audio cache entries cũ
        now = datetime.now()
        expired_keys = [
            k for k, v in audio_cache.items()
            if now - v['created_at'] > Config.AUDIO_CACHE_TIMEOUT
        ]
        for key in expired_keys:
            audio_cache.pop(key, None)

        if expired_keys:
            print(f"🗑️ Đã xóa {len(expired_keys)} audio cache entries")

@app.route('/uploads/<path:filename>')
def serve_uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ===================================================================
# Main Execution
# ===================================================================
if __name__ == "__main__":
    # ✅ THÊM: Migration cho vectorstores cũ
    from extensions import migrate_vectorstores_add_user_id

    migrate_vectorstores_add_user_id()
    migrate_batches_add_user_id()
    # Start background cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_scheduler, daemon=True)
    cleanup_thread.start()

    print("🚀 Server đang khởi động với kiến trúc Modular...")
    print("🔐 Authentication system đã được kích hoạt")
    print("🗄️ Database: SQLite (interviewer.db)")
    print("🔊 Text-to-Speech đã được kích hoạt")
    print(f"📁 Audio files được lưu tại: {Config.AUDIO_FOLDER}")
    print(f"📤 Upload folder: {Config.UPLOAD_FOLDER}")

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

    # Cleanup on exit
    cleanup_temp_files()