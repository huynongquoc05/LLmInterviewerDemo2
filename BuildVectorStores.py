import os
import time
import tempfile
from dotenv import load_dotenv
import nltk
from pymongo import MongoClient
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import hashlib

from config import Config
from extensions import embedding_manager

# ======================
# 1. Chuẩn bị NLTK
# ======================
nltk.download("punkt", quiet=True)
try:
    nltk.download("punkt_tab", quiet=True)
except:
    pass

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import NLTKTextSplitter, RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.schema import Document

# ======================
# Danh sách model hợp lệ với mô tả
# ======================
VALID_MODELS = {
    "intfloat/multilingual-e5-large-instruct": {
        "name": "Multilingual E5 Large Instruct",
        "languages": ["vi", "en", "multi"],
        "dimension": 1024,
        "description": "Model đa ngôn ngữ mạnh mẽ, tốt cho tiếng Việt"
    },
    "hiieu/halong_embedding": {
        "name": "hiieu/halong_embedding",
        "languages": ["vi"],
        "dimension": 768,
        "description": "Model tối ưu cho tiếng Việt"
    },
    "AITeamVN/Vietnamese_Embedding": {
        "name": "AITeamVN/Vietnamese_Embedding",
        "languages": ["vi"],
        "dimension": 1024,
        "description": "Model chuyên biệt cho tiếng Việt"
    }
}

# ======================
# Configuration
# ======================
# Thư mục lưu vectorstores (relative to this file)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_VECTORSTORES_DIR = os.path.join(PROJECT_ROOT, "vectorstores")


# ======================
# Text Splitter Strategy
# ======================
class TextSplitterStrategy:
    """Strategy pattern cho text splitting"""

    @staticmethod
    def get_splitter(strategy: str, chunk_size: int, chunk_overlap: int):
        if strategy == "nltk":
            return NLTKTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator="\n\n",
            )
        elif strategy == "recursive":
            return RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separators=["\n\n", "\n", ". ", " ", ""],
            )
        else:
            raise ValueError(f"Unknown strategy: {strategy}")


# ======================
# Utility Functions
# ======================
def calculate_file_hash(file_path: str) -> str:
    """Tính hash của file để detect duplicate"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def clean_text(text: str) -> str:
    """Làm sạch text trước khi embedding"""
    # Loại bỏ whitespace thừa
    text = " ".join(text.split())
    # Loại bỏ các ký tự đặc biệt không cần thiết
    text = text.replace("\x00", "")
    return text.strip()


def validate_pdf(pdf_path: str) -> Tuple[bool, Optional[str]]:
    """Validate PDF file"""
    if not os.path.exists(pdf_path):
        return False, "File không tồn tại"

    if not pdf_path.lower().endswith('.pdf'):
        return False, "File không phải định dạng PDF"

    file_size = os.path.getsize(pdf_path)
    max_size = 50 * 1024 * 1024  # 50MB
    if file_size > max_size:
        return False, f"File quá lớn (>{max_size / 1024 / 1024}MB)"

    if file_size == 0:
        return False, "File rỗng"

    return True, None


def check_duplicate_vectorstore(mongo_uri, file_hash, model_name, chunk_size, chunk_overlap, user_id=None):
    client = MongoClient(mongo_uri)
    db = client["interviewer_ai"]
    collection = db["vectorstores"]

    query = {
        "file_hash": file_hash,
        "model_name": model_name,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "status": "active"  # ✅ chỉ check bản đang hoạt động
    }

    if user_id:
        query["$or"] = [
            {"user_id": user_id},
            {"custom.user_id": user_id}
        ]

    existing = collection.find_one(query)
    return existing




# ======================
# Main Function - Improved
# ======================
def build_vectorstore(
        pdf_path: str,
        chunk_size: int = 1600,
        chunk_overlap: int = 400,
        model_name: str = "intfloat/multilingual-e5-large-instruct",
        mongo_uri: str = "mongodb://localhost:27017/",
        splitter_strategy: str = "nltk",
        skip_duplicate: bool = True,
        custom_metadata: Optional[Dict] = None,
        progress_callback: Optional[callable] = None,
        output_dir: Optional[str] = None  # NEW: Cho phép custom output dir
        ,user_id: Optional[str] = None  # ✅ THÊM
) -> Tuple[str, Dict]:
    """
    Build vectorstore với nhiều cải tiến

    Args:
        pdf_path: Đường dẫn file PDF
        chunk_size: Kích thước mỗi chunk
        chunk_overlap: Overlap giữa các chunk
        model_name: Tên model embedding
        mongo_uri: URI MongoDB
        splitter_strategy: Chiến lược chia văn bản ('nltk' hoặc 'recursive')
        skip_duplicate: Bỏ qua nếu đã tồn tại vectorstore giống hệt
        custom_metadata: Metadata tùy chỉnh
        progress_callback: Callback function để báo cáo tiến độ

    Returns:
        Tuple[save_path, metadata]
    """

    def report_progress(stage: str, progress: int):
        if progress_callback:
            progress_callback(stage, progress)

    # Validate model
    if model_name not in VALID_MODELS:
        raise ValueError(f"Model {model_name} không hợp lệ. Chọn từ: {list(VALID_MODELS.keys())}")

    # Validate PDF
    is_valid, error_msg = validate_pdf(pdf_path)
    if not is_valid:
        raise ValueError(f"PDF không hợp lệ: {error_msg}")

    report_progress("validation", 10)

    # Calculate file hash
    file_hash = calculate_file_hash(pdf_path)

    if skip_duplicate:
        existing = check_duplicate_vectorstore(
            mongo_uri,
            file_hash,
            model_name,
            chunk_size,
            chunk_overlap,
            user_id=user_id or (custom_metadata or {}).get("user_id")  # ✅ THÊM
        )
        if existing:
            print(f"⚠️ Vectorstore đã tồn tại (user_id={user_id}): {existing['vectorstore_name']}")
            return existing['vectorstore_path'], existing

    report_progress("loading", 20)

    # Load PDF
    try:
        loader = PyPDFLoader(pdf_path)
        pages = loader.load()
        print(f"📄 Đã load {len(pages)} trang từ PDF")
    except Exception as e:
        raise ValueError(f"Lỗi khi load PDF: {str(e)}")

    if not pages:
        raise ValueError("PDF không có nội dung")

    # Clean và merge text
    full_text = "\n".join([clean_text(p.page_content) for p in pages])
    full_doc = [Document(page_content=full_text, metadata={"source": pdf_path})]

    report_progress("splitting", 40)

    # Split text
    text_splitter = TextSplitterStrategy.get_splitter(
        splitter_strategy, chunk_size, chunk_overlap
    )

    splitted_docs = []
    for doc in full_doc:
        chunks = text_splitter.split_text(doc.page_content)
        for i, chunk in enumerate(chunks):
            splitted_docs.append({
                "page_content": clean_text(chunk),
                "metadata": {
                    **doc.metadata,
                    "chunk_index": i,
                    "chunk_size": len(chunk),
                    "splitter": splitter_strategy,

                }
            })

    print(f"✂️ Đã chia thành {len(splitted_docs)} chunks")

    # Filter empty chunks
    splitted_docs = [d for d in splitted_docs if len(d["page_content"].strip()) > 50]
    print(f"🔍 Sau khi lọc: {len(splitted_docs)} chunks hợp lệ")

    report_progress("embedding", 60)

    # ✅ Dùng cache để tránh load model nhiều lần
    device = "cpu"
    embeddings = embedding_manager.get_model(model_name, device)

    # Create vectorstore
    try:
        vectorstore = FAISS.from_texts(
            [d["page_content"] for d in splitted_docs],
            embeddings,
            metadatas=[d["metadata"] for d in splitted_docs],
        )
    except Exception as e:
        raise ValueError(f"Lỗi khi tạo vectorstore: {str(e)}")

    report_progress("saving", 80)

    # Save vectorstore
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Sử dụng output_dir nếu có, nếu không dùng default
    vectorstores_dir = output_dir or DEFAULT_VECTORSTORES_DIR
    os.makedirs(vectorstores_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    vs_name = f"vs_{base_name}_{timestamp}"
    save_path = os.path.join(vectorstores_dir, vs_name)

    vectorstore.save_local(save_path)
    print(f"💾 Vectorstore đã lưu tại: {save_path}")

    # Save metadata to MongoDB
    client = MongoClient(mongo_uri)
    db = client["interviewer_ai"]
    collection = db["vectorstores"]
    # === Chuẩn hóa đường dẫn PDF để lưu vào DB ===
    try:
        relative_pdf_path = os.path.relpath(pdf_path, Config.BASE_DIR).replace("\\", "/")
    except Exception:
        relative_pdf_path = pdf_path  # fallback nếu có lỗi
    pdf_path = relative_pdf_path
    metadata = {
        "pdf_file": os.path.basename(pdf_path),
        "num_pages":len(pages),
        "pdf_path": pdf_path,
        "file_hash": file_hash,
        "file_size_mb": os.path.getsize(pdf_path) / (1024 * 1024),
        "model_name": model_name,
        "model_info": VALID_MODELS[model_name],
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "splitter_strategy": splitter_strategy,
        "num_chunks": len(splitted_docs),
        "vectorstore_name": vs_name,
        "vectorstore_path": save_path,
        "created_at": datetime.utcnow(),
        "status": "active"
    }

    # Add custom metadata
    if custom_metadata:
        metadata["custom"] = custom_metadata
    metadata["user_id"] = custom_metadata.get("user_id")

    result = collection.insert_one(metadata)
    metadata["_id"] = str(result.inserted_id)

    print(f"✅ Metadata đã lưu vào MongoDB: {metadata['_id']}")

    report_progress("completed", 100)

    return save_path, metadata


# ======================
# Utility: List vectorstores
# ======================
def list_vectorstores(mongo_uri: str = "mongodb://localhost:27017/") -> List[Dict]:
    """Lấy danh sách tất cả vectorstores"""
    client = MongoClient(mongo_uri)
    db = client["interviewer_ai"]
    collection = db["vectorstores"]

    vectorstores = list(collection.find({"status": "active"}).sort("created_at", -1))

    for vs in vectorstores:
        vs["_id"] = str(vs["_id"])

    return vectorstores


# ======================
# Utility: Delete vectorstore
# ======================
def delete_vectorstore(
        vectorstore_id: str,
        mongo_uri: str = "mongodb://localhost:27017/",
        remove_files: bool = True
) -> bool:
    """Xóa hoàn toàn vectorstore khỏi DB và hệ thống file"""
    from bson import ObjectId
    import shutil

    client = MongoClient(mongo_uri)
    db = client["interviewer_ai"]
    collection = db["vectorstores"]

    vs = collection.find_one({"_id": ObjectId(vectorstore_id)})
    if not vs:
        print(f"⚠️ Không tìm thấy vectorstore {vectorstore_id}")
        return False

    # ✅ Xóa file trên ổ đĩa nếu có
    if remove_files and os.path.exists(vs["vectorstore_path"]):
        shutil.rmtree(vs["vectorstore_path"], ignore_errors=True)
        print(f"🗑️ Đã xóa files tại: {vs['vectorstore_path']}")
    else:
        print(f"⚠️ Không tìm thấy thư mục vectorstore: {vs['vectorstore_path']}")

    # ✅ Xóa bản ghi khỏi MongoDB
    result = collection.delete_one({"_id": ObjectId(vectorstore_id)})
    if result.deleted_count > 0:
        print(f"✅ Đã xóa bản ghi vectorstore {vectorstore_id} khỏi MongoDB")
        return True
    else:
        print(f"⚠️ Không xóa được bản ghi {vectorstore_id}")
        return False



# ======================
# Example usage
# ======================
if __name__ == "__main__":
    pdf_file = "example.pdf"

    if os.path.exists(pdf_file):
        save_path, metadata = build_vectorstore(
            pdf_path=pdf_file,
            chunk_size=1600,
            chunk_overlap=400,
            model_name="intfloat/multilingual-e5-large-instruct",
            splitter_strategy="nltk",
            skip_duplicate=True,
            custom_metadata={"category": "java", "topic": "advanced"}
        )

        print("\n" + "=" * 50)
        print("Vectorstore đã được tạo thành công!")
        print(f"Path: {save_path}")
        print(f"Metadata ID: {metadata['_id']}")
    else:
        print(f"File {pdf_file} không tồn tại")