from typing import Optional, List

from pymongo import MongoClient

from extensions import embedding_manager


def summarize_knowledge_with_llm(knowledge_text: str, topic: str, outline: list[str], llm):
    """
    Dùng LLM để tóm tắt và đánh giá chất lượng nguồn tài liệu RAG.
    """
    if not knowledge_text or len(knowledge_text.strip()) == 0:
        return {"summary": "(Không có tài liệu)", "quality_report": "Không có nội dung để đánh giá."}

    outline_str = "\n".join(f"- {item}" for item in outline or [])

    prompt = f"""
    Bạn là chuyên gia trong lĩnh vực liên quan đến {topic}, hãy giúp đánh giá và tóm tắt tài liệu phỏng vấn sau.
    
    CHỦ ĐỀ: {topic}
    OUTLINE (mục tiêu kiến thức): 
    {outline_str}

    --- TÀI LIỆU TRUY VẤN ---
    {knowledge_text}  # Giới hạn để tránh token overflow
    Đây là nguồn tài liệu truy vấn từ kỹ thuật RAG dựa trên từng  item in outline, mỗi item là 1 query
    HÃY TRẢ VỀ Bản tóm tắt 
    """

    result = llm.invoke(prompt)
    return result


import os
import pandas as pd
from datetime import datetime
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings


def build_cv_vectorstore_from_candidates(candidates, embedding_model=None, base_dir="vectorstores/cv"):
    """
    Tạo vectorstore FAISS cho danh sách thí sinh.
    """
    os.makedirs(base_dir, exist_ok=True)

    # 1️⃣ Load data
    if isinstance(candidates, str):
        df = pd.read_csv(candidates)
    else:
        df = pd.DataFrame(candidates)
    print(df.head(10))
    def row_to_text(row):
        return ", ".join(f"{col}: {val}" for col, val in row.items())

    texts = [row_to_text(r) for _, r in df.iterrows()]

    # 3️⃣ Nếu không truyền model thì tạo mới
    if embedding_model is None:
        embedding_model = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-large-instruct")

    # 4️⃣ Tạo và lưu vectorstore
    vectorstore = FAISS.from_texts(texts, embedding_model)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = os.path.join(base_dir, f"cv_{timestamp}")
    vectorstore.save_local(save_path)

    print(f"✅ CV Vectorstore saved to {save_path}")
    return save_path





import requests
import os
from GetApikey import get_api_key_elevenlab


# extension.py
from GetApikey import get_api_key_elevenlab
import requests

def generate_voice_ElevenLab(text, output_path="output.mp3"):
    """
    Sinh voice từ text bằng ElevenLabs.
    Trả về đường dẫn file nếu thành công, None nếu lỗi (vd hết limit).
    """
    API_KEY = get_api_key_elevenlab()
    if not API_KEY:
        return None

    url = "https://api.elevenlabs.io/v1/text-to-speech/pqHfZKP75CvOlQylNhV4"
    headers = {"xi-api-key": API_KEY, "Content-Type": "application/json"}
    data = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.8,
            "similarity_boost": 0.8
        },
        "voice_speed": 1.1
    }

    try:
        res = requests.post(url, json=data, headers=headers)
        if res.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(res.content)
            return output_path
        elif res.status_code == 429:
            print("⚠️ Hết limit ElevenLabs.")
            return None
        else:
            print(f"⚠️ Lỗi ElevenLabs: {res.status_code}")
            return None
    except Exception as e:
        print(f"⚠️ Lỗi gửi request ElevenLabs: {e}")
        return None


import requests
import os

def generate_voice_LocalTTS(
    text,
    output_path="output.mp3",
    voice="vi-VN-NamMinhNeural",
    speed=1.0,
    model="tts-1"
):
    """
    Sinh giọng nói từ text bằng container TTS local (chạy ở localhost:5050).
    Trả về đường dẫn file nếu thành công, None nếu lỗi.
    """
    try:
        # API endpoint & headers
        url = "http://localhost:5051/v1/audio/speech"
        api_key = "your_api_key_here"  # Cho phép lấy từ env
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        # Request body
        data = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": "mp3",
            "speed": speed
        }

        # Gửi request
        res = requests.post(url, headers=headers, json=data)

        # Xử lý phản hồi
        if res.status_code == 200:
            with open(output_path, "wb") as f:
                f.write(res.content)
            return output_path
        else:
            print(f"⚠️ Lỗi LocalTTS: {res.status_code} - {res.text}")
            return None

    except Exception as e:
        print(f"❌ Lỗi khi gọi LocalTTS: {e}")
        return None

import struct
from google import genai
from google.genai import types
from GetApikey import loadapi
from pydub import AudioSegment
import os

def generate_voice_Gemini_simple(text, output_path="gemini.mp3", voice="alnilam"):
    """
    Sinh voice từ Google Gemini bằng API non-stream.
    Convert audio raw L16 → WAV → MP3.
    """

    api_key = loadapi()
    if not api_key:
        print("❌ Không tìm thấy API Key Gemini.")
        return None

    try:
        client = genai.Client(api_key=api_key)
        model = "gemini-2.5-flash-preview-tts"

        res = client.models.generate_content(
            model=model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["audio"],  # chỉ cần audio
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice
                        )
                    )
                ),
            ),
        )

        # Lấy bytes raw PCM
        audio_bytes = res.candidates[0].content.parts[0].inline_data.data

        # --- tạo WAV header ---
        sample_rate = 24000  # Gemini L16 chuẩn 24kHz
        bits_per_sample = 16
        num_channels = 1
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8
        subchunk2_size = len(audio_bytes)
        chunk_size = 36 + subchunk2_size

        wav_header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            chunk_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            num_channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            subchunk2_size,
        )

        wav_path = output_path.replace(".mp3", ".wav")
        with open(wav_path, "wb") as f:
            f.write(wav_header)
            f.write(audio_bytes)

        # Convert WAV → MP3
        audio = AudioSegment.from_file(wav_path, format="wav")
        audio.export(output_path, format="mp3")
        os.remove(wav_path)

        return output_path

    except Exception as e:
        print(f"❌ Lỗi Gemini TTS: {e}")
        return None


def get_vectorstore_chunks(vectorstore_id, mongo_uri="mongodb://localhost:27017/"):
    """
    Trích xuất nội dung từng chunk trong vectorstore
    - Đọc metadata vectorstore từ MongoDB
    - Tự động chọn đúng model embedding
    - Trả về danh sách các đoạn văn bản (chunks)
    """
    from bson import ObjectId

    # Kết nối DB
    client = MongoClient(mongo_uri)
    db = client["interviewer_ai"]
    vs = db["vectorstores"].find_one({"_id": ObjectId(vectorstore_id)})

    if not vs:
        raise ValueError(f"Vectorstore {vectorstore_id} not found")

    # Lấy thông tin từ metadata
    path = vs.get("vectorstore_path")
    if not path:
        raise ValueError(f"Vectorstore {vectorstore_id} missing vectorstore_path")

    # Lấy model embedding chính xác từ metadata
    model_name = vs.get("model_name") or vs.get("model_info", {}).get("name")
    if not model_name:
        model_name = "intfloat/multilingual-e5-large-instruct"  # fallback an toàn

    # Khởi tạo embedding và load FAISS
    embeddings = embedding_manager.get_model(model_name=model_name, device="cpu")
    vs_local = FAISS.load_local(path, embeddings, allow_dangerous_deserialization=True)

    # Trích xuất nội dung các chunk
    docs = []
    for i, doc in enumerate(vs_local.docstore._dict.values()):
        docs.append({
            "index": i + 1,
            "content": doc.page_content,
            "metadata": doc.metadata or {},
        })

    return docs


class KnowledgeBuilder:
    """Xây dựng knowledge context có mở rộng ngữ cảnh và định dạng dễ đọc hơn."""

    def __init__(self, knowledge_db: Optional[FAISS] = None, fetch_surrounding: bool = True, window: int = 1):
        self._knowledge_db = knowledge_db
        self.retriever = None
        self.fetch_surrounding = fetch_surrounding
        self.window = window
        if knowledge_db:
            self.retriever = knowledge_db.as_retriever(search_kwargs={"k": 5})

    @property
    def knowledge_db(self):
        return self._knowledge_db

    @knowledge_db.setter
    def knowledge_db(self, value):
        self._knowledge_db = value
        if value:
            self.retriever = value.as_retriever(search_kwargs={"k": 5})
            print("🔄 retriever auto-updated from new knowledge_db")
        else:
            self.retriever = None
            print("⚠️ retriever cleared (knowledge_db=None)")

    def _fetch_surrounding_chunks(self, doc):
        """Lấy thêm các chunk liền kề (trước/sau) nếu có."""
        if not self.fetch_surrounding or "chunk_index" not in doc.metadata:
            return [doc]

        index = doc.metadata["chunk_index"]
        source = doc.metadata.get("source")
        all_docs = self.knowledge_db.docstore._dict.values()

        context_docs = [doc]
        for i in range(1, self.window + 1):
            prev_doc = next(
                (d for d in all_docs if d.metadata.get("source") == source and d.metadata.get("chunk_index") == index - i),
                None)
            next_doc = next(
                (d for d in all_docs if d.metadata.get("source") == source and d.metadata.get("chunk_index") == index + i),
                None)
            if prev_doc:
                context_docs.insert(0, prev_doc)
            if next_doc:
                context_docs.append(next_doc)
        return context_docs

    def build_context(self, topic: str, outline: Optional[List[str]] = None) -> str:
        """Tạo knowledge context với định dạng giúp LLM dễ đọc hơn."""
        results = []

        queries = outline if outline else [topic]
        for item in queries:
            query = f"{topic} {item}" if outline else item
            docs = self.retriever.invoke(query)
            for doc in docs:
                results.extend(self._fetch_surrounding_chunks(doc))

        # Loại trùng lặp
        seen = set()
        unique_docs = []
        for doc in results:
            if doc.page_content not in seen:
                seen.add(doc.page_content)
                unique_docs.append(doc)

        # 🔹 Định dạng context rõ ràng hơn
        formatted_sections = []
        for idx, doc in enumerate(unique_docs, 1):
            source = doc.metadata.get("source", "Không rõ nguồn")
            section = (
                f"### Mục {idx}\n"
                f"**Nguồn:** {source}\n"
                f"**Nội dung:**\n{doc.page_content.strip()}\n"
            )
            formatted_sections.append(section)

        knowledge_context = "\n\n---\n\n".join(formatted_sections)
        return knowledge_context

