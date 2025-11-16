# routes/interview_batch.py
"""
Routes quản lý batch (tạo, xóa, export, update status)
"""

import csv
from io import StringIO
from datetime import datetime
from flask import Blueprint, jsonify, request, Response
from bson import ObjectId, errors
from pymongo import DESCENDING
from langchain_community.vectorstores import FAISS

from BuildVectorStores import list_vectorstores
from config import Config
from extensions import db_batches, db_records, db_results, db_vectorstores, embedding_manager, llm_service
from extension import build_cv_vectorstore_from_candidates, summarize_knowledge_with_llm, KnowledgeBuilder

batch_bp = Blueprint('batch', __name__)

# routes/interview_batch.py (thêm sau imports)

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


@batch_bp.route("/create", methods=["POST"])
def create_interview_batch():
    """Tạo batch phỏng vấn mới"""

    # ✅ THÊM: Kiểm tra auth
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    try:
        data = request.json

        # Validate vectorstore_id
        try:
            vectorstore_id = ObjectId(data["vectorstore_id"])
        except (errors.InvalidId, TypeError):
            return jsonify({"success": False, "error": "ID không hợp lệ"}), 400

        vectorstore_info = db_vectorstores.find_one({"_id": vectorstore_id})
        if not vectorstore_info:
            return jsonify({
                "success": False,
                "error": f"Vectorstore {vectorstore_id} không tìm thấy"
            }), 404

        # ✅ THÊM: Kiểm tra ownership của vectorstore
        vs_user_id = vectorstore_info.get("user_id") or vectorstore_info.get("custom", {}).get("user_id")
        # ✅ Cho phép nếu vectorstore là public hoặc không gắn user
        is_public = vectorstore_info.get("is_public", False) or vectorstore_info.get("user_id") is None

        if not is_public and vs_user_id != user_id:
            return jsonify({
                "success": False,
                "error": "Permission denied - You cannot use this private vectorstore"
            }), 403

        # Load embedding model
        embedding_model_name = vectorstore_info["model_name"]
        embedding_model = embedding_manager.get_model(embedding_model_name)

        # Build CV vectorstore
        cv_vectorstore_path = build_cv_vectorstore_from_candidates(
            data["candidates"],
            embedding_model
        )

        # Load knowledge vectorstore
        knowledge_db = FAISS.load_local(
            vectorstore_info["vectorstore_path"],
            embedding_model,
            allow_dangerous_deserialization=True
        )

        # Build knowledge context
        knowledge_builder = KnowledgeBuilder(knowledge_db)
        knowledge_text = knowledge_builder.build_context(
            data["topic"],
            data.get("outline")
        )

        # Summarize knowledge
        report = summarize_knowledge_with_llm(
            knowledge_text,
            data["topic"],
            data.get("outline", []),
            llm_service
        )

        # Create batch document
        batch_doc = {
            "batch_name": data["session_name"],
            "config": data["config"],
            "candidates": data["candidates"],
            "cv_vectorstore_path": cv_vectorstore_path,
            "knowledge_vectorstore_path": vectorstore_info["vectorstore_path"],
            "embedding_model_name": embedding_model_name,
            "topic": data["topic"],
            "outline": data.get("outline", []),
            "knowledge_text": knowledge_text,
            "knowledge_summary": report,
            "created_at": datetime.utcnow().isoformat(),
            "status": "active",
            "completed_count": 0,
            "total_count": len(data["candidates"]),
            "user_id": user_id  # ← ✅ THÊM user_id
        }

        result = db_batches.insert_one(batch_doc)

        return jsonify({
            "success": True,
            "session_id": str(result.inserted_id),
            "message": "Đợt phỏng vấn đã được tạo!"
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@batch_bp.route("/list", methods=["GET"])
def list_interview_batches():
    """Lấy danh sách batches của user hiện tại"""

    # ✅ THÊM: Kiểm tra auth
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    # ✅ SỬA: Chỉ lấy batches của user này
    batches = list(
        db_batches.find(
            {"user_id": user_id},  # ← Filter theo user_id
            {"knowledge_text": 0, "knowledge_summary": 0}
        ).sort("created_at", DESCENDING)
    )

    for batch in batches:
        batch["_id"] = str(batch["_id"])

    return jsonify({"success": True, "sessions": batches})


@batch_bp.route("/get/<batch_id>", methods=["GET"])
def get_interview_batch(batch_id):
    """Lấy thông tin chi tiết batch"""

    # ✅ THÊM: Kiểm tra auth
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    include_knowledge = request.args.get('include_knowledge', 'false') == 'true'
    projection = {} if include_knowledge else {"knowledge_text": 0}

    batch = db_batches.find_one({"_id": ObjectId(batch_id)}, projection)
    if not batch:
        return jsonify({"success": False, "error": "Batch not found"}), 404

    # ✅ THÊM: Kiểm tra ownership
    if batch.get("user_id") != user_id:
        return jsonify({
            "success": False,
            "error": "Permission denied"
        }), 403

    batch["_id"] = str(batch["_id"])
    return jsonify({"success": True, "session": batch})


@batch_bp.route("/delete/<batch_id>", methods=["DELETE"])
def delete_interview_batch(batch_id):
    """Xóa batch (chỉ cho phép chủ sở hữu)"""

    # ✅ THÊM: Kiểm tra auth
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    # ✅ THÊM: Kiểm tra ownership
    batch = db_batches.find_one({"_id": ObjectId(batch_id)})
    if not batch:
        return jsonify({"success": False, "error": "Batch not found"}), 404

    if batch.get("user_id") != user_id:
        return jsonify({
            "success": False,
            "error": "Permission denied - You can only delete your own batches"
        }), 403

    # Xóa batch
    result = db_batches.delete_one({"_id": ObjectId(batch_id)})
    if result.deleted_count > 0:
        # Xóa các records liên quan
        db_records.delete_many({"batch_id": batch_id})
        return jsonify({"success": True})

    return jsonify({"success": False, "error": "Delete failed"}), 500


@batch_bp.route("/update_candidate_status", methods=["POST"])
def update_candidate_status():
    """Cập nhật status của candidate"""

    # ✅ THÊM: Kiểm tra auth
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    data = request.json

    # ✅ THÊM: Kiểm tra ownership
    batch = db_batches.find_one({"_id": ObjectId(data["session_id"])})
    if not batch:
        return jsonify({"success": False, "error": "Batch not found"}), 404

    if batch.get("user_id") != user_id:
        return jsonify({
            "success": False,
            "error": "Permission denied"
        }), 403

    db_batches.update_one(
        {"_id": ObjectId(data["session_id"]), "candidates.name": data["candidate_name"]},
        {
            "$set": {
                "candidates.$.status": data["status"],
                "candidates.$.completed_at": datetime.utcnow().isoformat()
            }
        }
    )

    if data["status"] == 'completed':
        batch = db_batches.find_one({"_id": ObjectId(data["session_id"])})
        completed_count = sum(1 for c in batch["candidates"] if c.get("status") == "completed")
        new_status = "completed" if completed_count == batch["total_count"] else "active"

        db_batches.update_one(
            {"_id": ObjectId(data["session_id"])},
            {
                "$set": {
                    "completed_count": completed_count,
                    "status": new_status
                }
            }
        )

    return jsonify({"success": True})


@batch_bp.route("/export/<batch_id>", methods=["GET"])
def export_batch_results(batch_id):
    """Export kết quả batch ra CSV"""

    # ✅ THÊM: Kiểm tra auth
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    batch = db_batches.find_one({"_id": ObjectId(batch_id)})
    if not batch:
        return jsonify({"error": "Batch not found"}), 404

    # ✅ THÊM: Kiểm tra ownership
    if batch.get("user_id") != user_id:
        return jsonify({"error": "Permission denied"}), 403

    results = []
    for candidate in batch["candidates"]:
        full_name = f"{candidate['name']},{candidate['class']}"
        result = db_results.find_one(
            {"candidate_info.name": full_name},
            sort=[("interview_stats.timestamp", DESCENDING)]
        )
        if result:
            results.append(result)

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Tên', 'Lớp', 'Điểm cuối cùng', 'Số câu hỏi', 'Trình độ', 'Thời gian', 'Trạng thái'])

    for res in results:
        name, *cls = res["candidate_info"]["name"].split(",")
        writer.writerow([
            name,
            ",".join(cls),
            res["interview_stats"].get("final_score", 0),
            res["interview_stats"].get("total_questions", 0),
            res["candidate_info"].get("classified_level", ""),
            res["interview_stats"].get("timestamp", ""),
            "Hoàn thành"
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename=results_{batch_id}.csv"}
    )


@batch_bp.route("/vectorstores", methods=["GET"])
def get_available_vectorstores():
    """Lấy danh sách vectorstores (riêng của user + dùng chung) để chọn khi tạo batch"""
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    try:
        from pymongo import DESCENDING

        # ✅ Lấy vectorstores của user + public
        vectorstores = list(
            db_vectorstores.find({
                "$or": [
                    {"custom.user_id": user_id},
                    {"user_id": user_id},
                    {"is_public": True},  # ✅ Thêm: cho phép dùng chung
                    {"user_id": None}     # ✅ fallback cho dữ liệu cũ (trước khi có is_public)
                ]
            }).sort("created_at", DESCENDING)
        )

        options = []
        for vs in vectorstores:
            options.append({
                "id": str(vs["_id"]),
                "name": vs.get("vectorstore_name", "Unnamed"),
                "path": vs.get("vectorstore_path"),
                "topic": vs.get("custom", {}).get("topic", "Unknown"),
                "pdf_file": vs.get("pdf_file", "Unknown"),
                "created_at": vs.get("created_at"),
                "num_chunks": vs.get("num_chunks", 0),
                "is_public": vs.get("is_public", vs.get("user_id") is None)
            })

        return jsonify({
            "success": True,
            "vectorstores": options,
            "count": len(options)
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
