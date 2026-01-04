# migration_add_roles.py
"""
Script này dùng để thêm cột 'role' vào bảng 'users' đã tồn tại.
Chạy file này MỘT LẦN duy nhất.
"""

import sqlite3
from contextlib import contextmanager

DATABASE_PATH = 'interviewer.db'


@contextmanager
def get_db():
    """Context manager cho database connection"""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Lỗi: {e}")
        raise e
    finally:
        conn.close()


def migrate_add_role_column():
    """
    Thực hiện di cư dữ liệu:
    1. Thêm cột 'role' với giá trị mặc định là 'user'.
    2. Cập nhật user có ID = 1 thành 'admin'.
    """
    print("Bắt đầu quá trình di cư dữ liệu...")
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # 1. Thêm cột 'role' vào bảng 'users'
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
                print("✅ Đã thêm cột 'role' vào bảng 'users'.")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e):
                    print("⚠️ Cột 'role' đã tồn PStại. Bỏ qua bước thêm cột.")
                else:
                    raise e

            # 2. Cập nhật vai trò cho user ID = 1
            cursor.execute("UPDATE users SET role = 'admin' WHERE id = 1")
            if cursor.rowcount > 0:
                print(f"✅ Đã cập nhật user ID = 1 thành 'admin'.")
            else:
                print("⚠️ Không tìm thấy user ID = 1 để cập nhật 'admin'.")

            # 3. Đảm bảo các user khác là 'user' (dù đã có default)
            cursor.execute("UPDATE users SET role = 'user' WHERE id != 1 AND role != 'admin'")
            print(f"✅ Đã đảm bảo {cursor.rowcount} user khác có vai trò 'user'.")

        print("\n🎉 Di cư dữ liệu thành công!")

    except Exception as e:
        print(f"\n❌ Lỗi nghiêm trọng khi di cư: {e}")


if __name__ == '__main__':
    migrate_add_role_column()