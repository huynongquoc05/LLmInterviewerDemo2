from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
import os

# ==== CẤU HÌNH ====
vectorstore_path = "vectorstores/cv/cv_20251030_195853"

# Model e5 (bạn có thể dùng 'intfloat/multilingual-e5-base' hoặc bản khác)
embedding_model_name = "intfloat/multilingual-e5-base"

# ==== LOAD EMBEDDINGS ====
embeddings = HuggingFaceEmbeddings(model_name=embedding_model_name)

# ==== LOAD VECTOR STORE ====
db = FAISS.load_local(
    vectorstore_path,
    embeddings,
    allow_dangerous_deserialization=True
)

# ==== LẤY TẤT CẢ CHUNK ====
# mỗi doc là 1 Document(page_content, metadata)
docs = db.docstore._dict.values()

# ==== HIỂN THỊ ====
for i, doc in enumerate(docs):
    print(f"--- Chunk {i+1} ---")
    print(doc.page_content[:500])  # in 500 ký tự đầu
    print("Metadata:", doc.metadata)
    print()
