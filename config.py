# config.py
import os
from datetime import timedelta


class Config:
    """Cấu hình toàn cục cho ứng dụng"""

    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-super-secret-key-change-in-production')  # ← THÊM
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB

    # Paths
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    AUDIO_FOLDER = os.path.join(BASE_DIR, 'temp_audio')
    ALLOWED_EXTENSIONS = {'pdf'}

    # MongoDB
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
    DB_NAME = 'interviewer_ai'

    # SQLite (cho authentication)  # ← THÊM
    SQLITE_DB = os.path.join(BASE_DIR, 'interviewer.db')

    # Audio
    AUDIO_CACHE_TIMEOUT = timedelta(hours=1)
    AUDIO_CLEANUP_INTERVAL = 30 * 60  # 30 minutes

    # AI Models
    LLM_MODEL = "gemini-2.5-flash"
    LLM_TEMPERATURE = 0.5
    DEFAULT_EMBEDDING_MODEL = 'intfloat/multilingual-e5-large-instruct'

    # Session  # ← THÊM
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Base path (cho deployment)
    @staticmethod
    def get_base_path(request):
        return '/iview1' if 'fit.neu.edu.vn' in request.host else ''

    @classmethod
    def init_folders(cls):
        """Tạo các thư mục cần thiết"""
        os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(cls.AUDIO_FOLDER, exist_ok=True)