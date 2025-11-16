# routes/audio.py
"""
Routes xử lý audio (TTS, streaming, cache)
"""

import os
import time
import uuid
from datetime import datetime
from flask import Blueprint, jsonify, send_file, request
from gtts import gTTS

from config import Config
from extensions import audio_cache
from utils import remove_code_blocks, detect_language
from extension import generate_voice_ElevenLab, generate_voice_LocalTTS,generate_voice_Gemini_simple as generate_voice_Gemini_MP3_web

audio_bp = Blueprint('audio', __name__)


def get_base_path():
    return '/iview1' if 'fit.neu.edu.vn' in request.host else ''


@audio_bp.route("/<audio_id>")
def serve_audio(audio_id):
    """Stream file audio"""
    if audio_id in audio_cache and os.path.exists(audio_cache[audio_id]['path']):
        return send_file(audio_cache[audio_id]['path'], mimetype="audio/mpeg")
    return jsonify({"error": "Audio file not found"}), 404


@audio_bp.route("/info/<audio_id>")
def audio_info(audio_id):
    """Lấy thông tin file audio"""
    if audio_id in audio_cache:
        info = audio_cache[audio_id].copy()
        info['created_at'] = info['created_at'].isoformat()
        info.pop('path', None)
        return jsonify(info)
    return jsonify({"error": "Audio not found"}), 404


@audio_bp.route("/test-tts", methods=["POST"])
def test_tts():
    """Test text-to-speech"""
    data = request.json
    text = data.get("text", "Xin chào, đây là bài test text-to-speech")
    lang = detect_language(text)
    audio_id = create_audio_from_text(text, lang)

    if audio_id:
        return jsonify({
            "success": True,
            "audio_id": audio_id,
            "audio_url": f"{get_base_path()}/audio/{audio_id}",
            "text": text,
            "language": lang
        })
    return jsonify({"success": False, "error": "Failed to create audio"}), 500


# ===================================================================
# Helper Function
# ===================================================================
def create_audio_from_text(text, lang='vi'):
    """
    Tạo file audio từ text với 3 tầng ưu tiên:
    1. Gemini TTS
    2. Local TTS
    3. gTTS (Google Translate)
    """
    try:
        clean_text = remove_code_blocks(text)
        if not clean_text:
            return None

        audio_id = str(uuid.uuid4())
        audio_filename = f"question_{audio_id}.mp3"
        audio_path = os.path.join(Config.AUDIO_FOLDER, audio_filename)

        # --- Ưu tiên 1: Gemini TTS ---
        start = time.time()
        gemini_audio_path = generate_voice_Gemini_MP3_web(clean_text, output_path=audio_path)
        end = time.time()
        print(f"🟣 Gemini TTS time: {end - start:.2f} seconds")
        if gemini_audio_path:
            source = 'gemini_tts'
        else:
            # --- Ưu tiên 2: Local TTS ---
            print("⚠️ Gemini TTS lỗi, fallback sang Local TTS...")
            start = time.time()
            local_audio_path = generate_voice_LocalTTS(clean_text, output_path=audio_path)
            end = time.time()
            print(f"🔵 LocalTTS time: {end - start:.2f} seconds")
            if local_audio_path:
                source = 'local_tts'
            else:
                # --- Ưu tiên 3: gTTS ---
                print("⚠️ Gemini & Local TTS lỗi, fallback sang gTTS...")
                tts = gTTS(text=clean_text, lang=lang, slow=False)
                tts.save(audio_path)
                source = 'gtts'

        # Lưu cache
        audio_cache[audio_id] = {
            'path': audio_path,
            'created_at': datetime.now(),
            'source': source,
            'text': clean_text
        }

        return audio_id

    except Exception as e:
        print(f"❌ Lỗi tạo audio: {e}")
        return None

# Export để dùng ở routes khác
__all__ = ['create_audio_from_text']