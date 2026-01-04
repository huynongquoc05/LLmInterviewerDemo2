# routes/administrator.py
"""
Blueprint cho Admin Dashboard
Chỉ user có role 'admin' mới truy cập được
"""

from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, Response
from functools import wraps
from bson import ObjectId
import json
from bson import json_util
import traceback  # Để in log lỗi chi tiết
from datetime import datetime

# Import DB
from extensions import db_vectorstores, db_batches, db_records
from database import get_all_users  # Import từ SQLite
from BuildVectorStores import delete_vectorstore  # Tận dụng hàm xóa từ file
from config import Config  # Import Config để dùng MONGO_URI khi xóa

admin_bp = Blueprint('admin', __name__)


# ===================================================================
# 1. DECORATOR BẢO VỆ
# ===================================================================

def admin_required(f):
    """
    Decorator để đảm bảo chỉ admin mới truy cập được route
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Kiểm tra đã login chưa
        if 'user' not in session:
            flash("Vui lòng đăng nhập để tiếp tục", "warning")
            return redirect(url_for('auth.login_page'))

        # 2. Kiểm tra có phải admin không
        if session['user'].get('role') != 'admin':
            flash("Bạn không có quyền truy cập trang này", "danger")
            return redirect(url_for('static.index'))  # Chuyển về trang chủ

        return f(*args, **kwargs)

    return decorated_function


# ===================================================================
# 2. ROUTE CHÍNH CỦA ADMIN (HIỂN THỊ)
# ===================================================================

@admin_bp.route('/')
@admin_required
def dashboard():
    """
    Hiển thị trang dashboard chính của Admin
    (ĐÃ TỐI ƯU: Chỉ tải thông tin tóm tắt)
    """
    try:
        # --- 1. Lấy map User ID -> Tên (Từ SQLite) ---
        all_users = get_all_users()
        user_map = {user['id']: user['name'] for user in all_users}
        user_map[None] = "Public (Không ai sở hữu)"

        # --- 2. Thống kê Vectorstores (Từ MongoDB) ---
        pipeline_vs = [
            {
                "$group": {
                    "_id": {"$ifNull": ["$user_id", "$custom.user_id"]},
                    "total_stores": {"$sum": 1},
                    "total_size_mb": {"$sum": "$file_size_mb"},
                    "total_chunks": {"$sum": "$num_chunks"}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        vectorstore_stats_raw = list(db_vectorstores.aggregate(pipeline_vs))

        vectorstore_stats = []
        for stat in vectorstore_stats_raw:
            user_id = stat['_id']
            vectorstore_stats.append({
                "user_id": user_id,
                "user_name": user_map.get(user_id, f"User ID {user_id} (Đã xóa)"),
                "total_stores": stat['total_stores'],
                "total_size_mb": round(stat.get('total_size_mb', 0), 2),
                "total_chunks": stat.get('total_chunks', 0)
            })

        # --- 3. Thống kê Batches (Từ MongoDB) ---
        pipeline_batch = [
            {
                "$group": {
                    "_id": "$user_id",
                    "total_batches": {"$sum": 1},
                    "total_candidates": {"$sum": "$total_count"},
                    "total_completed": {"$sum": "$completed_count"}
                }
            },
            {"$sort": {"_id": 1}}
        ]
        batch_stats_raw = list(db_batches.aggregate(pipeline_batch))

        batch_stats = []
        for stat in batch_stats_raw:
            user_id = stat['_id']
            batch_stats.append({
                "user_id": user_id,
                "user_name": user_map.get(user_id, f"User ID {user_id} (Đã xóa)"),
                "total_batches": stat['total_batches'],
                "total_candidates": stat.get('total_candidates', 0),
                "total_completed": stat.get('total_completed', 0)
            })

        # --- 4. Lấy TẤT CẢ Vectorstores (Giữ nguyên) ---
        all_vectorstores_raw = list(db_vectorstores.find().sort("created_at", -1))
        all_vectorstores = []
        for vs in all_vectorstores_raw:
            user_id = vs.get('user_id') or vs.get('custom', {}).get('user_id')
            vs['owner_name'] = user_map.get(user_id, f"ID {user_id}")
            all_vectorstores.append(vs)

        # --- 5. Lấy TÓM TẮT Batches (Đã tối ưu) ---
        # Chỉ lấy các trường cần thiết cho bảng
        projection = {
            "_id": 1,
            "batch_name": 1,
            "topic": 1,
            "completed_count": 1,
            "total_count": 1,
            "status": 1,
            "user_id": 1
        }
        # SỬA: Thêm {} làm filter rỗng (lấy tất cả), projection là param thứ 2
        all_batches_raw = list(db_batches.find({}, projection).sort("created_at", -1))
        print(f"Số batch lấy được: {len(all_batches_raw)}")

        all_batches = []
        for batch in all_batches_raw:
            user_id = batch.get('user_id')
            batch['owner_name'] = user_map.get(user_id, f"ID {user_id}")
            all_batches.append(batch)

        # --- 6. Render Template ---
        # KHÔNG CẦN "làm sạch" (sanitize) bất cứ gì nữa
        # Vì all_vectorstores cần datetime cho strftime
        # Và all_batches không còn được dùng với |tojson
        #In dữ liệu batch tóm tawt
        print(len(all_batches))
        for batch in all_batches:
            print(f"dữ liệu batch: {batch} ")
        return render_template(
            "admin/dashboard.html",
            vectorstore_stats=vectorstore_stats,
            batch_stats=batch_stats,
            all_vectorstores=all_vectorstores,
            all_batches=all_batches
        )

    except Exception as e:
        print("\n===== LỖI KHI TẢI ADMIN DASHBOARD =====")
        traceback.print_exc()
        print("=======================================\n")
        flash(f"Lỗi nghiêm trọng khi tải dashboard: {e}", "danger")
        return render_template(
            "admin/dashboard.html",
            vectorstore_stats=[],
            batch_stats=[],
            all_vectorstores=[],
            all_batches=[]
        )


# ===================================================================
# 3. ROUTE HÀNH ĐỘNG (XÓA) - (Giữ nguyên)
# ===================================================================

@admin_bp.route('/delete/vectorstore/<string:vectorstore_id>', methods=['POST'])
@admin_required
def delete_vectorstore_admin(vectorstore_id):
    """
    Admin xóa bất kỳ vectorstore nào (bỏ qua kiểm tra ownership)
    """
    try:
        success = delete_vectorstore(
            vectorstore_id,
            mongo_uri=Config.MONGO_URI,
            remove_files=True
        )
        if success:
            flash(f"Đã xóa Vectorstore ID: {vectorstore_id}", "success")
        else:
            flash(f"Lỗi khi xóa Vectorstore ID: {vectorstore_id}", "danger")

    except Exception as e:
        flash(f"Lỗi nghiêm trọng khi xóa vectorstore: {e}", "danger")

    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/delete/batch/<string:batch_id>', methods=['POST'])
@admin_required
def delete_batch_admin(batch_id):
    """
    Admin xóa bất kỳ batch nào (bỏ qua kiểm tra ownership)
    """
    try:
        result = db_batches.delete_one({"_id": ObjectId(batch_id)})

        if result.deleted_count > 0:
            deleted_records = db_records.delete_many({"batch_id": batch_id})
            flash(f"Đã xóa Batch ID: {batch_id} và {deleted_records.deleted_count} bản ghi phỏng vấn", "success")
        else:
            flash(f"Không tìm thấy Batch ID: {batch_id} để xóa", "warning")

    except Exception as e:
        flash(f"Lỗi nghiêm trọng khi xóa batch: {e}", "danger")

    return redirect(url_for('admin.dashboard'))


# ===================================================================
# 4. ROUTE API MỚI (Lấy chi tiết Batch)
# ===================================================================

@admin_bp.route('/batch_info/<string:batch_id>')
@admin_required
def get_batch_info(batch_id):
    """
    API endpoint để lấy thông tin chi tiết của 1 batch
    """
    try:
        batch = db_batches.find_one({"_id": ObjectId(batch_id)})

        if not batch:
            return jsonify({"error": "Batch not found"}), 404

        # Sử dụng json_util.dumps để chuyển đổi ObjectId, datetime
        # sang chuỗi JSON an toàn
        safe_data = json_util.dumps(batch)

        # Trả về Response với mimetype application/json
        return Response(safe_data, mimetype='application/json')

    except Exception as e:
        print(f"Lỗi khi lấy batch info (ID: {batch_id}): {e}")
        return jsonify({"error": str(e)}), 500