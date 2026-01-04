# database.py
"""
Database models và setup cho SQLite
"""

import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from contextlib import contextmanager

DATABASE_PATH = 'interviewer.db'


@contextmanager
def get_db():
    """Context manager cho database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row  # Cho phép truy cập bằng tên cột
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# database.py

def init_db():
    """Khởi tạo database và các bảng"""
    with get_db() as conn:
        cursor = conn.cursor()

        # Bảng users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT,
                google_id TEXT UNIQUE,
                avatar_url TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login TEXT,
                login_method TEXT NOT NULL,  -- 'password' hoặc 'google'

                -- THÊM DÒNG NÀY --
                role TEXT NOT NULL DEFAULT 'user', -- Thêm cột role

                CONSTRAINT email_unique UNIQUE (email)
            )
        ''')
        # ... (phần còn lại của hàm) ...

        # Bảng sessions (optional - để tracking sessions)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_token TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')

        conn.commit()
        print("✅ Database initialized successfully")


# ===================================================================
# User Model Functions
# ===================================================================

def create_user(email, name, password=None, google_id=None, avatar_url=None):
    """
    Tạo user mới
    - Nếu có password: login_method = 'password'
    - Nếu có google_id: login_method = 'google'
    - Email luôn là UNIQUE
    """
    with get_db() as conn:
        cursor = conn.cursor()

        # Kiểm tra email đã tồn tại chưa
        cursor.execute('SELECT id FROM users WHERE email = ?', (email,))
        if cursor.fetchone():
            raise ValueError(f"Email {email} đã được đăng ký")

        password_hash = generate_password_hash(password) if password else None
        login_method = 'google' if google_id else 'password'

        cursor.execute('''
            INSERT INTO users (email, name, password_hash, google_id, avatar_url, 
                             created_at, login_method)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (email, name, password_hash, google_id, avatar_url,
              datetime.utcnow().isoformat(), login_method))

        user_id = cursor.lastrowid
        return get_user_by_id(user_id)


def get_user_by_email(email):
    """Lấy user theo email"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ? AND is_active = 1', (email,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id):
    """Lấy user theo ID"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = ? AND is_active = 1', (user_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_user_by_google_id(google_id):
    """Lấy user theo Google ID"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE google_id = ? AND is_active = 1', (google_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def verify_password(user, password):
    """Xác thực mật khẩu"""
    if not user or not user.get('password_hash'):
        return False
    return check_password_hash(user['password_hash'], password)


def update_last_login(user_id):
    """Cập nhật thời gian đăng nhập cuối"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET last_login = ? 
            WHERE id = ?
        ''', (datetime.utcnow().isoformat(), user_id))


def link_google_account(user_id, google_id, avatar_url=None):
    """
    Liên kết tài khoản Google với user đã tồn tại
    (Dùng khi user đăng ký bằng password trước, sau đó login bằng Google)
    """
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET google_id = ?, avatar_url = ?, login_method = 'google'
            WHERE id = ?
        ''', (google_id, avatar_url, user_id))


def update_password(user_id, new_password):
    """Cập nhật mật khẩu mới"""
    password_hash = generate_password_hash(new_password)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE users 
            SET password_hash = ?
            WHERE id = ?
        ''', (password_hash, user_id))


def get_all_users():
    """Đọc và trả về tất cả các bản ghi từ bảng users."""
    try:
        # Sử dụng context manager get_db() để kết nối và quản lý giao dịch
        with get_db() as conn:
            cursor = conn.cursor()

            # Thực thi lệnh SQL
            cursor.execute(
                "SELECT id, email, name, avatar_url, is_active, created_at, last_login, login_method FROM users")

            # Lấy tất cả kết quả
            users = cursor.fetchall()

            # Chuyển đổi các đối tượng sqlite3.Row thành danh sách các dictionary để dễ sử dụng hơn
            # Hoặc bạn có thể trả về trực tiếp đối tượng Row
            return [dict(user) for user in users]

    except Exception as e:
        print(f"Lỗi khi đọc bản ghi users: {e}")
        return []

if __name__ == '__main__':
    init_db()
    all_users= get_all_users()
    for user in all_users:
        print(user)