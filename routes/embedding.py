# routes/embedding.py
"""
Routes quản lý vectorstore (upload, list, delete, chunks)
"""

import os
import json
import time
import threading
import traceback
from datetime import datetime
from flask import Blueprint, jsonify, request, Response, stream_with_context
from werkzeug.utils import secure_filename
from bson import ObjectId, json_util

from config import Config
from extensions import db_vectorstores
from utils import allowed_file
from BuildVectorStores import build_vectorstore, list_vectorstores, delete_vectorstore, VALID_MODELS
from extension import get_vectorstore_chunks

embedding_bp = Blueprint('embedding', __name__)

# routes/embedding.py (thêm vào đầu file sau imports)

from flask import session  # ← Thêm import

def get_current_user_id():
    """Lấy user_id từ session"""
    user = session.get('user')
    if not user:
        return None
    return user.get('id')

def require_auth():
    """Kiểm tra user đã login chưa"""
    if not session.get('user'):
        return jsonify({
            "success": False,
            "error": "Unauthorized - Please login",
            "redirect": "/login"
        }), 401
    return None


@embedding_bp.route("/upload", methods=["POST"])
def upload_pdf():
    """Upload PDF và tạo vectorstore với progress streaming"""

    # ✅ THÊM: Kiểm tra auth
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    if 'pdf_file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['pdf_file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"error": "Invalid file"}), 400

    chunk_size = int(request.form.get('chunk_size', 1600))
    chunk_overlap = int(request.form.get('chunk_overlap', 400))
    model_name = request.form.get('model_name', Config.DEFAULT_EMBEDDING_MODEL)
    splitter_strategy = request.form.get('splitter_strategy', 'nltk')

    if model_name not in VALID_MODELS:
        return jsonify({"error": f"Invalid model: {model_name}"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(
        Config.UPLOAD_FOLDER,
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
    )
    file.save(filepath)

    def generate():
        try:
            yield f"data: {json.dumps({'status': 'processing', 'stage': 'init', 'progress': 0})}\n\n"

            def run_and_stream():
                save_path, metadata = build_vectorstore(
                    pdf_path=filepath,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    model_name=model_name,
                    mongo_uri=Config.MONGO_URI,
                    splitter_strategy=splitter_strategy,
                    skip_duplicate=True,
                    custom_metadata={
                        "uploaded_filename": filename,
                        "original_path": os.path.relpath(filepath, Config.UPLOAD_FOLDER).replace("\\", "/"),
                        "user_id": user_id
                    },
                    user_id=user_id,  # ✅ THÊM
                    progress_callback=lambda s, p: queue.append(
                        f"data: {json.dumps({'status': 'processing', 'stage': s, 'progress': p})}\n\n"
                    ),
                )

                # ✅ CHẶN LỖI ObjectId
                from datetime import datetime
                from bson import ObjectId

                def convert_bson(obj):
                    if isinstance(obj, ObjectId):
                        return str(obj)
                    if isinstance(obj, datetime):  # ✅ THÊM
                        return obj.isoformat()  # chuyển datetime sang chuỗi ISO8601
                    if isinstance(obj, dict):
                        return {k: convert_bson(v) for k, v in obj.items()}
                    if isinstance(obj, list):
                        return [convert_bson(v) for v in obj]
                    return obj

                safe_metadata = convert_bson(metadata)

                queue.append(f"data: {json_util.dumps({'status': 'completed', 'progress': 100, 'metadata': safe_metadata})}\n\n")

            queue = []
            thread = threading.Thread(target=run_and_stream)
            thread.start()

            while thread.is_alive() or queue:
                while queue:
                    yield queue.pop(0)
                time.sleep(0.3)

        except Exception as e:
            yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )


@embedding_bp.route("/list", methods=["GET"])
def list_vectorstores_route():
    """Lấy danh sách vectorstores của user hiện tại + các vectorstore chung"""

    # ✅ Kiểm tra xác thực
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    try:
        from pymongo import DESCENDING

        # ✅ Bao gồm:
        # - vectorstore của user hiện tại
        # - vectorstore có user_id == None (public)
        vectorstores = list(
            db_vectorstores.find({
                "$or": [
                    {"user_id": user_id},
                    {"custom.user_id": user_id},
                    {"user_id": None},
                    {"user_id": {"$exists": False}}  # Phòng khi record cũ chưa có field user_id
                ]
            }).sort("created_at", DESCENDING)
        )

        # ✅ Chuẩn hóa ObjectId và flag public
        for vs in vectorstores:
            vs["_id"] = str(vs["_id"])
            vs["is_public"] = vs.get("user_id") is None

        return jsonify({
            "success": True,
            "vectorstores": vectorstores,
            "count": len(vectorstores)
        })

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@embedding_bp.route("/delete/<vectorstore_id>", methods=["DELETE"])
def delete_vectorstore_route(vectorstore_id):
    """Xóa vectorstore (chỉ cho phép chủ sở hữu)"""

    # ✅ THÊM: Kiểm tra auth
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    try:
        # ✅ THÊM: Kiểm tra ownership trước khi xóa
        vs = db_vectorstores.find_one({"_id": ObjectId(vectorstore_id)})

        if not vs:
            return jsonify({
                "success": False,
                "message": "Vectorstore not found"
            }), 404

        # Kiểm tra user_id (có thể ở custom hoặc top level)
        vs_user_id = vs.get("user_id") or vs.get("custom", {}).get("user_id")

        if vs_user_id != user_id:
            return jsonify({
                "success": False,
                "message": "Permission denied - You can only delete your own vectorstores"
            }), 403

        # Xóa vectorstore
        success = delete_vectorstore(
            vectorstore_id,
            mongo_uri=Config.MONGO_URI,
            remove_files=True
        )

        if success:
            return jsonify({"success": True, "message": "Vectorstore deleted"})

        return jsonify({
            "success": False,
            "message": "Delete failed"
        }), 500

    except Exception as e:
        # ✅ Ghi log chi tiết lỗi ra console
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
@embedding_bp.route("/models", methods=["GET"])
def get_models():
    """Lấy danh sách các embedding models"""
    return jsonify({"success": True, "models": VALID_MODELS})

@embedding_bp.route("/info/<vectorstore_id>", methods=["GET"])
def get_vectorstore_info(vectorstore_id):
    """Lấy thông tin chi tiết vectorstore"""
    vs = db_vectorstores.find_one({"_id": ObjectId(vectorstore_id)})
    if not vs:
        return jsonify({"success": False, "message": "Vectorstore not found"}), 404
    vs["_id"] = str(vs["_id"])
    return jsonify({"success": True, "vectorstore": vs})

@embedding_bp.route("/chunks/<vectorstore_id>", methods=["GET"])
def get_vectorstore_chunks_route(vectorstore_id):
    """Lấy các chunks của vectorstore"""
    try:
        chunks = get_vectorstore_chunks(vectorstore_id)
        return jsonify({"success": True, "chunks": chunks})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500