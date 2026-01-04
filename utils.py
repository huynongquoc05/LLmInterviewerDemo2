# utils.py
"""
Các hàm tiện ích dùng chung
"""

import os
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from enum import Enum
from config import Config

# ===================================================================
# File Utilities
# ===================================================================
def allowed_file(filename):
    """Kiểm tra file upload có hợp lệ không"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def clean_old_audio_files():
    """Xóa các file audio cũ hơn 1 giờ"""
    try:
        now = datetime.now()
        for filename in os.listdir(Config.AUDIO_FOLDER):
            file_path = os.path.join(Config.AUDIO_FOLDER, filename)
            if os.path.isfile(file_path):
                file_time = datetime.fromtimestamp(os.path.getctime(file_path))
                if now - file_time > Config.AUDIO_CACHE_TIMEOUT:
                    os.remove(file_path)
    except Exception as e:
        print(f"Lỗi khi xóa file audio cũ: {e}")

def cleanup_temp_files():
    """Xóa tất cả file tạm"""
    try:
        for filename in os.listdir(Config.AUDIO_FOLDER):
            file_path = os.path.join(Config.AUDIO_FOLDER, filename)
            os.remove(file_path)
    except Exception as e:
        print(f"Lỗi khi xóa file tạm: {e}")

# ===================================================================
# Text Processing
# ===================================================================
def remove_code_blocks(text: str) -> str:
    """Loại bỏ code blocks khỏi text để tạo audio"""
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    for code_block in soup.find_all(["pre", "code"]):
        code_block.decompose()
    clean_text = soup.get_text(separator=" ", strip=True)
    return re.sub(r'\s+', ' ', clean_text).strip()

def detect_language(text):
    """Phát hiện ngôn ngữ (vi/en)"""
    vietnamese_chars = "àáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵđ"
    return 'vi' if any(char in text for char in vietnamese_chars + vietnamese_chars.upper()) else 'en'

# ===================================================================
# Data Serialization
# ===================================================================
def to_mongo_safe(obj):
    """Chuyển đổi Enum thành giá trị string cho MongoDB"""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, list):
        return [to_mongo_safe(i) for i in obj]
    if isinstance(obj, dict):
        return {k: to_mongo_safe(v) for k, v in obj.items()}
    return obj

from bson import ObjectId

def to_json_safe(obj):
    """Chuyển đổi ObjectId thành string cho JSON response"""
    if isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: to_json_safe(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_json_safe(i) for i in obj]
    return obj