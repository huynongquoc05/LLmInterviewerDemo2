# routes/interview_process.py
"""
Routes xử lý tiến trình phỏng vấn (start, answer, resume)
"""

import re
from dataclasses import asdict
from datetime import datetime
from flask import Blueprint, jsonify, request
from bson import ObjectId
from langchain_community.vectorstores import FAISS

from config import Config
from extensions import (
    db_batches, db_records,
    embedding_manager, interview_processor, context_cache
)
from utils import to_mongo_safe, to_json_safe
from routes.audio import create_audio_from_text
from LLMInterviewer4 import (
    InterviewConfig, InterviewContext, InterviewRecord,
    classify_level_from_score, Level, QuestionDifficulty,
    InterviewPhase, QuestionAttempt
)

interview_bp = Blueprint('interview', __name__)


def get_base_path():
    return '/iview1' if 'fit.neu.edu.vn' in request.host else ''


# routes/interview_process.py (thêm vào đầu file)

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


def verify_batch_ownership(batch_id: str, user_id: int):
    """Kiểm tra user có quyền truy cập batch này không"""
    from extensions import db_batches
    batch = db_batches.find_one({"_id": ObjectId(batch_id)})

    if not batch:
        return False

    return batch.get("user_id") == user_id
# ===================================================================
# Context Wakeup (Cache)
# ===================================================================
def wakeup_context(batch_id: str):
    """
    Load context cho batch (cached để tái sử dụng)
    Returns: (cv_db, context)
    """
    if batch_id in context_cache:
        return context_cache[batch_id]

    batch_info = db_batches.find_one({"_id": ObjectId(batch_id)})
    if not batch_info:
        raise ValueError(f"Không tìm thấy batch ID: {batch_id}")

    # Load embedding model (cached)
    embedding_model = embedding_manager.get_model(batch_info["embedding_model_name"])

    # Load CV vectorstore
    cv_db = FAISS.load_local(
        batch_info["cv_vectorstore_path"],
        embedding_model,
        allow_dangerous_deserialization=True
    )

    # Build context
    context = InterviewContext(
        topic=batch_info["topic"],
        outline=batch_info["outline"],
        knowledge_text=batch_info["knowledge_text"],
        outline_summary=batch_info["knowledge_summary"],
        config=InterviewConfig(**batch_info["config"])
    )

    # Cache it
    context_cache[batch_id] = (cv_db, context)
    print(f"⚡ Cache context cho batch {batch_id} (topic: {batch_info['topic']})")

    return cv_db, context


# ===================================================================
# Start/Resume Interview
# ===================================================================
@interview_bp.route("/start_candidate", methods=["POST"])
def start_candidate_interview():
    """
    Bắt đầu hoặc tiếp tục phỏng vấn
    """
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    try:
        data = request.json
        batch_id = data["session_id"]
        candidate_name = data["candidate_name"]  # ✅ Chỉ cần tên

        # ✅ THAY ĐỔI: Không verify ownership của batch
        if not verify_batch_ownership(batch_id, user_id):
            return jsonify({
                "success": False,
                "error": "Permission denied - You can only access your own interview batches"
            }), 403

        # ✅ BƯỚC 1: Tìm record đã tồn tại (dùng candidate_name trực tiếp)
        existing_record = db_records.find_one({
            "batch_id": batch_id,
            "candidate_name": candidate_name  # ✅ Không cần thêm class
        })

        # ✅ BƯỚC 2: Nếu đã hoàn thành → Trả về summary
        if existing_record and existing_record.get("is_finished"):
            return jsonify({
                "success": True,
                "already_completed": True,
                "record_id": str(existing_record["_id"]),
                "summary": {
                    "candidate_info": {
                        "name": candidate_name,  # ✅ Chỉ tên
                        "classified_level": existing_record.get("classified_level", "")
                    },
                    "interview_stats": {
                        "final_score": existing_record.get("final_score", 0),
                        "total_questions": existing_record.get("total_questions_asked", 0),
                        "timestamp": existing_record.get("created_at", "")
                    },
                    "question_history": [
                        {
                            "question_number": idx + 1,
                            "difficulty": q["difficulty"],
                            "question": q["question"],
                            "answer": q["answer"],
                            "score": q["score"],
                            "analysis": q["analysis"],
                            "time_limit": q.get("time_limit", 60),
                            "time_spent": q.get("time_spent", 0)
                        }
                        for idx, q in enumerate(existing_record.get("history", []))
                    ]
                }
            })

        # ✅ BƯỚC 3-6: Wakeup context & tạo record mới
        cv_db, context = wakeup_context(batch_id)

        # ✅ Query CV vectorstore bằng tên trực tiếp
        profile_docs = cv_db.similarity_search(candidate_name, k=1)
        if not profile_docs:
            return jsonify({"error": f"Không tìm thấy hồ sơ {candidate_name}"}), 404

        profile_text = profile_docs[0].page_content

        # ✅ Classify level từ điểm
        score_match = re.search(r'Điểm 40%[:\s]+([0-9.]+)', profile_text)
        level = classify_level_from_score(float(score_match.group(1))) if score_match else Level.TRUNG_BINH

        # ✅ Tạo record mới
        new_record, first_q_data = interview_processor.start_new_record(
            batch_id,
            candidate_name,  # ✅ Chỉ cần tên
            profile_text,
            level,
            context
        )

        record_dict = to_mongo_safe(asdict(new_record))

        if existing_record:
            record_dict["created_at"] = existing_record.get("created_at")
            record_dict["reset_count"] = existing_record.get("reset_count", 0) + 1
            record_dict["last_reset_at"] = datetime.utcnow().isoformat()

            db_records.replace_one(
                {"_id": existing_record["_id"]},
                record_dict
            )
            record_id = str(existing_record["_id"])
            print(f"🔄 Reset record cho {candidate_name} (lần {record_dict['reset_count']})")
        else:
            result = db_records.insert_one(record_dict)
            record_id = str(result.inserted_id)
            print(f"🆕 Tạo record mới cho {candidate_name}")

        # ✅ Tạo audio
        audio_id = create_audio_from_text(first_q_data["question"])

        return jsonify({
            "success": True,
            "already_completed": False,
            "record_id": record_id,
            "question": first_q_data["question"],
            "difficulty": first_q_data["difficulty"],
            "time_limit": first_q_data["time_limit"],
            "level": level.value,
            "phase": "warmup",
            "audio_id": audio_id,
            "audio_url": f"{get_base_path()}/audio/{audio_id}" if audio_id else None,
            "is_resumed": existing_record is not None and not existing_record.get("is_finished")
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
# ===================================================================
# Answer Question
# ===================================================================
@interview_bp.route("/answer", methods=["POST"])
def answer():
    """Xử lý câu trả lời và sinh câu hỏi tiếp theo"""

    # ✅ THÊM: Kiểm tra auth
    auth_error = require_auth()
    if auth_error:
        return auth_error

    user_id = get_current_user_id()

    try:
        data = request.json
        print(f"📩 Dữ liệu FE gửi đến vào lúc {datetime.utcnow()}:", data)

        record_id = data["record_id"]
        answer_text = data["answer"]
        time_spent = data.get("time_spent", 0)

        # ✅ Load record từ MongoDB
        record_data = db_records.find_one({"_id": ObjectId(record_id)})
        if not record_data:
            return jsonify({
                "error": f"Luợt phỏng vấn không hợp lệ"
            }), 404

        # ✅ THÊM: Kiểm tra ownership qua batch_id
        batch_id = record_data.get("batch_id")
        if not verify_batch_ownership(batch_id, user_id):
            return jsonify({
                "success": False,
                "error": "Permission denied"
            }), 403

        # ✅ Deserialize
        record_data.pop('_id', None)
        try:
            record_data['history'] = [
                QuestionAttempt(**{**att, "difficulty": QuestionDifficulty(att["difficulty"])})
                for att in record_data['history']
            ]
            record_data['classified_level'] = Level(record_data['classified_level'])
            record_data['current_difficulty'] = QuestionDifficulty(record_data['current_difficulty'])
            record_data['current_phase'] = InterviewPhase(record_data['current_phase'])
        except Exception as e:
            return jsonify({"error": f"Lỗi dữ liệu bản ghi: {e}"}), 500

        record_data.pop("reset_count", None)
        record_data.pop("last_reset_at", None)
        record = InterviewRecord(**record_data)

        # ✅ Wake up context
        _, context = wakeup_context(record.batch_id)

        # ✅ Process answer (truyền time_spent vào)
        updated_record, api_result = interview_processor.process_answer(
            record, context, answer_text, time_spent
        )

        # ✅ Update MongoDB
        record_dict = to_mongo_safe(asdict(updated_record))
        db_records.replace_one({"_id": ObjectId(record_id)}, record_dict)

        # ✅ MỚI: Nếu finished, trả về closing_message riêng
        if api_result.get("finished"):
            # api_result["summary"] đã chứa closing_message từ processor
            return jsonify({
                "finished": True,
                "closing_message": api_result["summary"].get("closing_message", "Cảm ơn bạn đã tham gia!"),
                "summary": api_result["summary"]  # Vẫn gửi summary để FE dùng sau
            })

        # ✅ Sinh audio cho câu hỏi tiếp theo (nếu chưa finished)
        if "next_question" in api_result:
            audio_id = create_audio_from_text(api_result["next_question"])
            if audio_id:
                api_result["audio_id"] = audio_id
                api_result["audio_url"] = f"{get_base_path()}/audio/{audio_id}"

        return jsonify(to_json_safe(api_result))

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500