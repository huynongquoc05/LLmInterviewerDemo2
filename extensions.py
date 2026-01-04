# extensions.py
"""
Khởi tạo các service toàn cục (LLM, Embedding, DB)
Load một lần duy nhất khi ứng dụng khởi động
"""

from pymongo import MongoClient
from langchain_google_genai import GoogleGenerativeAI
from langchain_huggingface import HuggingFaceEmbeddings
from GetApikey import loadapi
from config import Config

# ===================================================================
# MongoDB Connection
# ===================================================================
client = MongoClient(Config.MONGO_URI)
db = client[Config.DB_NAME]

# Collections
db_batches = db["interview_batches"]
db_records = db["interview_records"]
# db_results = db["interview_results"]
db_vectorstores = db["vectorstores"]

# ===================================================================
# LLM Service (Google Gemini)
# ===================================================================
llm_service = GoogleGenerativeAI(
    model=Config.LLM_MODEL,
    temperature=Config.LLM_TEMPERATURE,
    google_api_key=loadapi()
)


# ===================================================================
# Embedding Manager (Cache models)
# ===================================================================
class EmbeddingModelManager:
    """Quản lý và cache các model embedding"""

    def __init__(self):
        self._cache = {}

    def get_model(self, model_name: str, device: str = "cpu"):
        if model_name not in self._cache:
            print(f"⏳ Đang load embedding model: {model_name}...")
            self._cache[model_name] = HuggingFaceEmbeddings(
                model_name=model_name,
                model_kwargs={'device': device},
                encode_kwargs={'device': device}
            )
            print(f"✅ Model {model_name} đã được load và cache.")
        return self._cache[model_name]


embedding_manager = EmbeddingModelManager()


# extensions.py (thêm vào cuối file)

def migrate_vectorstores_add_user_id():
    """Migration: Thêm user_id vào các vectorstore cũ"""
    try:
        result = db_vectorstores.update_many(
            {"user_id": {"$exists": False}},  # Các record chưa có user_id
            {"$set": {"user_id": None}}  # Set = None (hoặc admin ID)
        )
        if result.modified_count > 0:
            print(f"✅ Migrated {result.modified_count} vectorstores")
    except Exception as e:
        print(f"⚠️ Migration error: {e}")

# extensions.py (thêm vào cuối file)

def migrate_batches_add_user_id():
    """Migration: Thêm user_id vào các batch cũ"""
    try:
        result = db_batches.update_many(
            {"user_id": {"$exists": False}},
            {"$set": {"user_id": None}}  # Hoặc set = admin ID
        )
        if result.modified_count > 0:
            print(f"✅ Migrated {result.modified_count} batches")
    except Exception as e:
        print(f"⚠️ Migration error: {e}")

# ===================================================================
# Interview Processor
# ===================================================================
from LLMInterviewer4 import InterviewProcessor

interview_processor = InterviewProcessor(llm=llm_service)

# ===================================================================
# Audio Cache
# ===================================================================
audio_cache = {}

# ===================================================================
# Context Cache (cho wakeup_context)
# ===================================================================
context_cache = {}

print("✅ Extensions đã được khởi tạo thành công!")
