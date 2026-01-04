

import os
import random
from dotenv import load_dotenv


def loadapi():
    # Load biến môi trường từ file .env
    load_dotenv()

    # 1. Tạo danh sách các key cần lấy
    potential_keys = [
        os.getenv("GOOGLE_API_KEY"),
        os.getenv("GOOGLE_API_KEY1"),
        os.getenv("GOOGLE_API_KEY2")
    ]

    # 2. Lọc danh sách để loại bỏ các giá trị None hoặc rỗng (phòng trường hợp bạn chưa điền đủ 3 key)
    valid_keys = [key for key in potential_keys if key and key.strip()]

    # 3. Kiểm tra xem có key nào hợp lệ không
    if not valid_keys:
        print("❌ Lỗi: Không tìm thấy bất kỳ API Key nào trong file .env")
        return None

    # 4. Chọn ngẫu nhiên 1 key từ danh sách hợp lệ
    selected_key = random.choice(valid_keys)

    # (Tùy chọn) In ra để debug xem đang dùng key nào (chỉ in 4 số cuối)
    # print(f"🔑 Đang dùng Key đuôi: ...{selected_key[-4:]}")

    return selected_key

def get_api_key_elevenlab():
    load_dotenv()
    API_KEY = os.getenv("Elevenlabs_API_KEY")
    return API_KEY