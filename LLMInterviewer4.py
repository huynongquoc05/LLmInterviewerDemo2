# LLMInterviewer4.py - COMPLETE VERSION
# ======================================
# PHIÊN BẢN 3.0: CORE LOGIC PHI TRẠNG THÁI (STATELESS)
#
# KIẾN TRÚC:
# - File này chỉ chứa business logic thuần túy, không I/O, không load model.
# - Lớp `InterviewProcessor` là một dịch vụ phi trạng thái. Nó nhận trạng thái (Record, Context),
#   xử lý, và trả về trạng thái mới.
# - Toàn bộ việc quản lý trạng thái (load/save từ DB), quản lý model AI,
#   và xử lý request/response được chuyển cho `app.py`.

import datetime
import hashlib
import re
import json
from dataclasses import dataclass, asdict, field
from enum import Enum
from typing import List, Dict, Optional, Tuple

from langchain_google_genai import GoogleGenerativeAI


# =======================
# 1. Enums & Data Classes
# =======================

class Level(Enum):
    YEU = "yeu"
    TRUNG_BINH = "trung_binh"
    KHA = "kha"
    GIOI = "gioi"
    XUAT_SAC = "xuat_sac"


class QuestionDifficulty(Enum):
    VERY_EASY = "very_easy"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    VERY_HARD = "very_hard"


class InterviewPhase(Enum):
    WARMUP = "warmup"
    TECHNICAL = "technical"
    CLOSING = "closing"


@dataclass
class QuestionAttempt:
    question: str
    answer: str
    score: float
    analysis: str
    difficulty: QuestionDifficulty
    timestamp: str
    question_hash: Optional[str] = None
    time_limit: Optional[int] = None  # ✅ THÊM FIELD MỚI
    time_spent: Optional[int] = None   # ✅ THÊM: thời gian thí sinh dùng (giây)


@dataclass
class InterviewConfig:
    """Cấu hình cho một đợt phỏng vấn."""
    threshold_high: float = 7.0
    threshold_low: float = 4.0
    max_attempts_per_level: int = 2
    max_total_questions: int = 8
    max_upper_level: int = 2
    llm_temperature: float = 0.5
    max_memory_turns: int = 6
    max_warmup_questions: int = 2
    difficulty_map: Dict[Level, List[QuestionDifficulty]] = field(default_factory=lambda: {
        Level.YEU: [QuestionDifficulty.VERY_EASY, QuestionDifficulty.EASY],
        Level.TRUNG_BINH: [QuestionDifficulty.EASY, QuestionDifficulty.EASY],
        Level.KHA: [QuestionDifficulty.MEDIUM, QuestionDifficulty.HARD],
        Level.GIOI: [QuestionDifficulty.MEDIUM, QuestionDifficulty.VERY_HARD],
        Level.XUAT_SAC: [QuestionDifficulty.MEDIUM, QuestionDifficulty.VERY_HARD],
    })


@dataclass
class InterviewContext:
    """
    Bối cảnh chung cho cả một đợt phỏng vấn (Batch).
    Thông tin này không đổi giữa các thí sinh.
    """
    topic: str
    outline: Optional[List[str]]
    knowledge_text: str
    outline_summary: str
    config: InterviewConfig


@dataclass
class InterviewRecord:
    """
    Bản ghi trạng thái của một luợt phỏng vấn cho một thí sinh.
    Đây là đối tượng được load và save liên tục từ/vào DB.
    """
    batch_id: str
    candidate_name: str
    candidate_profile: str
    candidate_context: str
    classified_level: Level
    current_difficulty: QuestionDifficulty
    current_phase: InterviewPhase
    attempts_at_current_level: int
    total_questions_asked: int
    upper_level_reached: int
    warmup_questions_asked: int
    history: List[QuestionAttempt]
    conversation_memory: List[Dict]  # Thay thế cho đối tượng ConversationMemory
    is_finished: bool
    final_score: Optional[float] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())


# =======================
# 2. Utility Functions
# =======================

def classify_level_from_score(score_40: float) -> Level:
    """Phân loại level dựa trên điểm 40%"""
    if score_40 < 5.0:
        return Level.YEU
    elif score_40 <= 6.5:
        return Level.TRUNG_BINH
    elif score_40 <= 8.0:
        return Level.KHA
    elif score_40 <= 9.0:
        return Level.GIOI
    else:
        return Level.XUAT_SAC


def get_initial_difficulty(level: Level, config: InterviewConfig) -> QuestionDifficulty:
    """Lấy độ khó ban đầu cho level"""
    return config.difficulty_map[level][0]


def calculate_question_hash(question: str) -> str:
    """Calculate hash của câu hỏi để detect duplicate"""
    return hashlib.md5(question.encode()).hexdigest()


def _sanitize_question(q: str) -> str:
    """Làm sạch chuỗi câu hỏi khỏi ký tự thừa, dấu số thứ tự, backtick..."""
    s = str(q or "").strip()
    s = re.sub(r'^[`\"]+|[`\"]+$', '', s)
    s = re.sub(r'^\s*"\s*', '', s)
    s = re.sub(r'^\s*\(?\d+\)?[\).\s:-]+\s*', '', s)
    s = s.rstrip(",;}]")
    return s.strip()


def _extract_fallback_question(text: str) -> str:
    """Cố gắng trích câu hỏi nếu JSON lỗi."""
    # Thử bắt đoạn "question": "..."
    m = re.search(r'"question"\s*:\s*"([\s\S]+?)"\s*}', text)
    if m:
        return m.group(1)
    # Nếu không có, lấy dòng dài nhất
    quoted = re.findall(r'"([^"]{20,})"', text, flags=re.S)
    if quoted:
        return quoted[0]
    lines = [ln.strip() for ln in text.splitlines() if len(ln.strip()) > 30]
    return max(lines, key=len) if lines else text


def _clean_and_parse_json_response(raw_text: str, expected_keys: list = None) -> dict:
    """Parse JSON response từ LLM với fallback handling"""
    if not raw_text:
        return {}

    text = raw_text.strip()

    # Gỡ code fence nếu có
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = text.rstrip("`").strip("`").strip()

    # Lấy phần JSON chính
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        q = _extract_fallback_question(text)
        return {"question": _sanitize_question(q)}

    json_str = text[start:end + 1]

    # Parse JSON an toàn
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        q = _extract_fallback_question(json_str)
        return {"question": _sanitize_question(q)}
    except Exception as e:
        print("⚠️ Lỗi parse JSON:", e)
        q = _extract_fallback_question(json_str)
        return {"question": _sanitize_question(q)}

    # Chuẩn hóa câu hỏi
    if isinstance(parsed, dict) and "question" in parsed:
        q = parsed["question"]
        q = _sanitize_question(q)
        return {"question": q}

    # Fallback cuối
    q = _extract_fallback_question(text)
    return {"question": _sanitize_question(q)}


def _parse_evaluation_response(raw_text: str) -> dict:
    """Parse JSON kết quả chấm điểm từ LLM"""
    if not raw_text:
        return {}

    text = raw_text.strip()

    # Loại bỏ code block
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = text.rstrip("`").strip("`").strip()

    # Tìm đoạn JSON trong chuỗi
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        json_str = text[start:end + 1]
        try:
            return json.loads(json_str)
        except Exception as e:
            print("⚠️ Parse JSON lỗi:", e)
            return {}

    return {}


# =======================
# 3. Memory Manager (Helper Class)
# =======================

class ConversationMemory:
    """
    Lớp tiện ích tạm thời để quản lý memory trong một lần xử lý.
    Nó được tạo ra từ `conversation_memory` lưu trong `InterviewRecord`.
    """

    def __init__(self, history: List[Dict], max_turns: int):
        self.memory = history
        self.max_turns = max_turns

    def add(self, role: str, content: str):
        self.memory.append({"role": role, "content": content})
        self.memory = self.memory[-self.max_turns:]

    def build_prompt(self) -> str:
        if not self.memory:
            return ""
        return "\n".join([f"{m['role']}: {m['content']}" for m in self.memory])

    def get_history(self) -> List[Dict]:
        """Lấy list history để lưu lại vào InterviewRecord."""
        return self.memory


# =======================
# 4. Component Workers
# =======================

class WarmupManager:
    """Component quản lý giai đoạn warm-up"""

    def __init__(self, llm: GoogleGenerativeAI):
        self.llm = llm

    def generate_warmup_question(
            self,
            candidate_name: str,
            candidate_context: str,
            topic: str,
            warmup_count: int
    ) -> Dict:  # ✅ ĐỔI: Trả về Dict
        """Tạo câu hỏi warm-up dựa trên context của thí sinh"""

        warmup_templates = {
            0: f"""
Bạn là interviewer AI thân thiện và chuyên nghiệp.

THÔNG TIN THÍ SINH:
{candidate_context}

Hãy chào hỏi và giới thiệu về buổi phỏng vấn. Bao gồm:
1. Chào thí sinh bằng tên
2. Giới thiệu chủ đề: "{topic}"
3. Đặt 1 câu hỏi warm-up nhẹ nhàng về kinh nghiệm/sở thích liên quan đến {topic}

YÊU CẦU:
- Thân thiện, tạo không khí thoải mái
- Câu hỏi dễ trả lời, KHÔNG cần kiến thức sâu
- Giúp thí sinh "làm nóng máy" trước khi vào phần chuyên môn

OUTPUT: JSON
{{"question": "lời chào + câu hỏi warm-up"}}
""",
            1: f"""
Bạn là interviewer AI thân thiện, đang tiếp tục phần warm-up với thí sinh {candidate_name}.

THÔNG TIN THÍ SINH:
{candidate_context}

Câu hỏi trước đã giúp bạn hiểu sơ qua về ứng viên.
Bây giờ, hãy đặt thêm 1 câu hỏi warm-up mới về:
- Động lực học {topic}
- Mục tiêu nghề nghiệp
- Cách ứng viên có thể áp dụng {topic} trong học tập hoặc công việc

YÊU CẦU:
- KHÔNG chào lại thí sinh (không dùng "Chào..." ở đầu)
- Có thể bắt đầu bằng câu chuyện tiếp tự nhiên:
  "Cảm ơn chia sẻ rất thú vị của bạn, ..."
  "Nghe thật hay, tiếp theo tôi muốn hỏi thêm..."
- Giữ giọng thân thiện, ngắn gọn, không đi sâu kỹ thuật

OUTPUT: JSON
{{"question": "câu hỏi warm-up thứ 2, có lời chuyển mượt"}}
"""
        }

        prompt = warmup_templates.get(warmup_count, warmup_templates[1])
        result = self.llm.invoke(prompt)
        parsed = _clean_and_parse_json_response(result)

        question = parsed.get("question", f"Xin chào {candidate_name}! Bạn đã sẵn sàng cho buổi phỏng vấn chưa?")

        # ✅ Trả về dict với time_limit cố định cho warmup
        return {
            "question": question,
            "difficulty": "warmup",
            "time_limit": 90  # Warmup: 90 giây (thoải mái hơn technical)
        }

    def extract_candidate_context(self, profile: str) -> str:
        """
        Trích xuất thông tin quan trọng từ CV/profile để LLM hiểu về thí sinh
        Returns: Tóm tắt ngắn gọn về thí sinh (200-300 từ)
        """
        lines = profile.split('\n')
        summary_lines = []
        keywords = ['tên', 'lớp', 'điểm', 'kỹ năng', 'dự án', 'kinh nghiệm', 'sở thích']

        for line in lines[:15]:
            if any(kw in line.lower() for kw in keywords):
                summary_lines.append(line)

        context = '\n'.join(summary_lines[:10])
        return context if context else profile[:500]

class QuestionGenerator:
    """Component chuyên generate câu hỏi"""

    def __init__(self, llm: GoogleGenerativeAI):
        self.llm = llm

    def _estimate_time_limit(self, difficulty: QuestionDifficulty, question: str) -> int:
        """Tính thời gian gợi ý dựa trên độ khó + có code hay không."""
        base_times = {
            QuestionDifficulty.VERY_EASY: 30,
            QuestionDifficulty.EASY: 45,
            QuestionDifficulty.MEDIUM: 70,
            QuestionDifficulty.HARD: 100,
            QuestionDifficulty.VERY_HARD: 140,
        }

        time_limit = base_times[difficulty]

        # Nếu câu hỏi yêu cầu phân tích code → cộng thêm 30 giây
        if "<pre><code" in question:
            time_limit += 30

        return time_limit

    def generate_with_context(
            self,
            topic: str,
            difficulty: QuestionDifficulty,
            knowledge_text: str,
            memory: ConversationMemory,
            candidate_context: str,
            outline_summary: str = ""
    ) -> Dict:  # ✅ ĐỔI: Trả về Dict thay vì str
        """Generate câu hỏi có nhận thức về thí sinh."""

        difficulty_descriptions = {
            QuestionDifficulty.VERY_EASY: (
                "rất cơ bản – kiểm tra sự hiểu biết nền tảng: khái niệm, định nghĩa, hoặc ví dụ minh họa đơn giản. "
                "Câu trả lời ngắn (1–2 câu), không yêu cầu phân tích sâu. "
                "Nếu chủ đề liên quan đến lập trình hoặc kỹ thuật, có thể hỏi về cú pháp, chức năng, hoặc mục đích sử dụng cơ bản."
            ),
            QuestionDifficulty.EASY: (
                "cơ bản – yêu cầu người học giải thích ý nghĩa, so sánh, hoặc nêu ví dụ thực tế nhỏ. "
                "Nếu chủ đề thuộc lĩnh vực kỹ thuật, có thể bao gồm một đoạn mã ngắn (dưới 10 dòng) hoặc tình huống kỹ thuật đơn giản để phân tích."
            ),
            QuestionDifficulty.MEDIUM: (
                "trung cấp – kiểm tra khả năng vận dụng kiến thức vào tình huống cụ thể, hoặc phân tích mối liên hệ giữa các khái niệm. "
                "Nếu là lĩnh vực phi kỹ thuật, câu hỏi có thể yêu cầu trình bày quan điểm, phân tích nguyên nhân – kết quả, hoặc đánh giá tình huống. "
                "Nếu là lĩnh vực lập trình, có thể yêu cầu phân tích một đoạn code (15–25 dòng) hoặc mô tả cách giải quyết một vấn đề thực tế nhỏ."
            ),
            QuestionDifficulty.HARD: (
                "nâng cao – yêu cầu tư duy phản biện, đánh giá hoặc tổng hợp thông tin từ nhiều nguồn. "
                "Thường liên quan đến việc giải thích quyết định, đề xuất giải pháp, hoặc so sánh các phương pháp. "
                "Nếu chủ đề kỹ thuật, có thể yêu cầu thiết kế mô-đun hoặc phân tích hiệu năng của giải pháp."
            ),
            QuestionDifficulty.VERY_HARD: (
                "rất khó – đòi hỏi năng lực tổng hợp, sáng tạo hoặc ứng dụng vào tình huống phức tạp, có nhiều biến số. "
                "Câu hỏi thường mở, không có câu trả lời duy nhất, và khuyến khích người học lập luận logic hoặc đưa ra quan điểm có dẫn chứng. "
                "Nếu chủ đề là lập trình hoặc kỹ thuật, có thể mô phỏng một hệ thống hoàn chỉnh hoặc bài toán thiết kế lớn."
            )
        }

        history_text = memory.build_prompt()

        prompt = f"""
        Bạn là một **Interviewer AI chuyên nghiệp và giàu kinh nghiệm**, được huấn luyện để đánh giá năng lực ứng viên qua phỏng vấn kỹ thuật.

        =====================
        THÔNG TIN THÍ SINH
        =====================
        {candidate_context}

        =====================
        CHỦ ĐỀ PHỎNG VẤN
        =====================
        {topic}

        =====================
        LỊCH SỬ HỘI THOẠI (gần đây)
        =====================
        {history_text or "Chưa có lịch sử hội thoại"}

        =====================
        TÀI LIỆU THAM KHẢO
        =====================
        Tài liệu có thể rất dài. Hãy đọc chọn lọc và tập trung vào phần LIÊN QUAN đến câu hỏi mới.
        {knowledge_text if knowledge_text else "Không có tài liệu"}

        
        
        =====================
        NHIỆM VỤ
        =====================
        Tạo ra **một câu hỏi phỏng vấn cá nhân hóa** cho thí sinh ở độ khó:
        ➡️{difficulty.value} {difficulty_descriptions[difficulty]}

        Câu hỏi cần:
        1. Phù hợp với năng lực và phong cách trả lời trước đây của thí sinh.  
           - Nếu thí sinh còn yếu, hãy dùng ngôn từ khích lệ và gợi mở.  
           - Nếu thí sinh giỏi, đặt câu hỏi thách thức hơn, yêu cầu phân tích sâu.  
        2. Có thể bao gồm ví dụ code thực tế, rõ ràng, dùng thẻ:
           <pre><code class='language-java'>...</code></pre>
        3. Có cấu trúc tự nhiên:
           - (a) Lời nhận xét hoặc chuyển tiếp ngắn gọn từ câu trước.
           - (b) Câu hỏi chính (liên quan tới topic).
           - (c) Một câu gợi mở tùy chọn nếu muốn khuyến khích thí sinh mở rộng.
        5. Không trùng lặp với các câu hỏi trong lịch sử hội thoại.
        6. Giữ giọng văn thân thiện, chuyên nghiệp.
        7. Lưu ý quan trọng: 
        - Với những câu hỏi dạng lý thuyết/ khái niệm , chỉ đưa ra câu hỏi khi chắc chắn tìm được câu trả lời trong tài liệu.
        - hãy chú ý tránh hỏi những gì mà tài liệu bị đánh giá là thiếu sót dựa vào bản tóm tắt của llm.
        
        =====================
        TÓM TẮT HOẶC OUTLINE
        =====================
        {outline_summary or "Không có"}
        
        =====================
        ĐỊNH DẠNG ĐẦU RA
        =====================
        Trả về JSON hợp lệ duy nhất dạng:

        {{
          "question": "<nội dung câu hỏi>",
          "difficulty": "{difficulty.value}",
          "time_limit": <số giây thí sinh nên dành để trả lời>
        }}

        ⚠️ Không thêm mô tả, không trả về văn bản ngoài JSON.
        """
        print(f"Đang tạo câu hỏi độ khó {difficulty.value}...")
        result = self.llm.invoke(prompt)
        parsed = _clean_and_parse_json_response(result)

        question = parsed.get("question", "Bạn có thể giải thích thêm được không?")

        # Format code blocks
        question = re.sub(
            r"<pre><code([^>]*)>([\s\S]*?)</code></pre>",
            lambda m: f"<pre><code{m.group(1)}>{m.group(2).replace('<br>', '\n')}</code></pre>",
            question
        )

        # ✅ Nếu LLM không trả time_limit → tự tính
        if "time_limit" not in parsed or not parsed["time_limit"]:
            time_limit = self._estimate_time_limit(difficulty, question)
        else:
            time_limit = int(parsed["time_limit"])

        # ✅ Trả về dict đầy đủ
        return {
            "question": question,
            "difficulty": difficulty.value,
            "time_limit": time_limit
        }

class AnswerEvaluator:
    """Component chuyên chấm điểm câu trả lời"""

    def __init__(self, llm: GoogleGenerativeAI):
        self.llm = llm

    def evaluate(
            self,
            question: str,
            answer: str,
            knowledge_text: str
    ) -> Tuple[float, str]:
        """Đánh giá câu trả lời chi tiết, có thang điểm rõ ràng và phân tích ngắn."""

        # Nếu knowledge quá dài, rút gọn nhưng thông báo cho LLM biết
        # truncated_knowledge = knowledge_text
        # if len(knowledge_text) > 10000:
        #     truncated_knowledge = knowledge_text[:8000] + "\n\n...(tài liệu bị rút gọn, chỉ hiển thị phần đầu)..."

        prompt = f"""
    Bạn là **giám khảo phỏng vấn kỹ thuật chuyên nghiệp**, nhiệm vụ của bạn là **chấm điểm câu trả lời của ứng viên** dựa trên **tài liệu tham khảo**.

    ========================
    CÂU HỎI:
    ========================
    {question}

    ========================
    CÂU TRẢ LỜI CỦA ỨNG VIÊN:
    ========================
    {answer}

    ========================
    TÀI LIỆU THAM KHẢO:
    ========================
    {knowledge_text or "Không có tài liệu"}

    ========================
    HƯỚNG DẪN CHẤM ĐIỂM:
    ========================
    1️⃣ **Xác định các ý chính** trong câu trả lời (liệt kê 2–5 ý quan trọng).
    2️⃣ **Đối chiếu từng ý** với tài liệu tham khảo:
       - ✅ "Khớp chính xác / đúng trọng tâm" → 2 điểm mỗi ý
       - ⚙️ "Đúng một phần hoặc mở rộng hợp lý ngoài tài liệu" → 1 điểm mỗi ý
       - ❌ "Sai hoặc không liên quan" → 0 điểm
    3️⃣ **Tổng hợp điểm /10**:
       - Điểm = (điểm trung bình các ý) × 10 / 2 (giới hạn 0–10)
       - Nếu không đủ dữ kiện để đánh giá → 5.0 điểm mặc định.
    4️⃣ Đưa ra **nhận xét ngắn gọn (1–3 câu)**:
       - Nêu điểm mạnh và điểm cần cải thiện.
       - Viết giọng khách quan, mang tính khích lệ.

    ========================
    ĐỊNH DẠNG KẾT QUẢ TRẢ VỀ:
    ========================
    Trả về JSON hợp lệ duy nhất như sau:

    {{
      "score": <float 0-10>,
      "analysis": "<phân tích ngắn gọn, 1–3 câu>"
    }}

    ⚠️ Không trả về text khác ngoài JSON.
    """

        try:
            result = self.llm.invoke(prompt)
            parsed = _parse_evaluation_response(result)

            score = float(parsed.get("score", 5.0))
            analysis = parsed.get("analysis", "Không có nhận xét")

            # Chuẩn hóa điểm
            score = max(0.0, min(10.0, score))

            return score, analysis

        except Exception as e:
            print(f"⚠️ Lỗi khi chấm điểm: {e}")
            return 5.0, "Lỗi khi chấm điểm, mặc định 5/10"


class DifficultyAdapter:
    """Component điều chỉnh độ khó"""

    def decide_next_action(self, score: float, config: InterviewConfig) -> str:
        """Quyết định action tiếp theo"""
        if score >= config.threshold_high:
            return "harder"
        if score >= config.threshold_low:
            return "same"
        return "easier"

    def get_next_difficulty(
            self,
            current: QuestionDifficulty,
            action: str
    ) -> QuestionDifficulty:
        """Tính độ khó tiếp theo"""
        difficulties = list(QuestionDifficulty)
        current_idx = difficulties.index(current)

        if action == "harder" and current_idx < len(difficulties) - 1:
            return difficulties[current_idx + 1]
        if action == "easier" and current_idx > 0:
            return difficulties[current_idx - 1]
        return current


# =======================
# 5. BỘ XỬ LÝ LOGIC PHỎNG VẤN (STATELESS PROCESSOR)
# =======================

class InterviewProcessor:
    """
    Bộ xử lý logic phỏng vấn phi trạng thái.
    Nó nhận trạng thái, xử lý, và trả về trạng thái mới.
    Không tự mình load model hay kết nối DB.
    """

    def __init__(self, llm: GoogleGenerativeAI):
        """Khởi tạo processor với các dependency cần thiết (LLM)."""
        self.llm = llm

        # Khởi tạo các component worker
        self.warmup_manager = WarmupManager(self.llm)
        self.question_generator = QuestionGenerator(self.llm)
        self.answer_evaluator = AnswerEvaluator(self.llm)
        self.difficulty_adapter = DifficultyAdapter()

    def start_new_record(
            self,
            batch_id: str,
            candidate_name: str,
            candidate_profile: str,
            classified_level: Level,
            context: InterviewContext
    ) -> Tuple[InterviewRecord, Dict]:  # ✅ ĐỔI: Trả về Dict thay vì str
        """
        Khởi tạo một bản ghi phỏng vấn mới cho thí sinh.

        Returns:
            - InterviewRecord: Đối tượng bản ghi trạng thái ban đầu.
            - Dict: {
                "question": str,
                "difficulty": str,
                "time_limit": int
              }
        """
        config = context.config
        initial_difficulty = get_initial_difficulty(classified_level, config)
        candidate_context = self.warmup_manager.extract_candidate_context(candidate_profile)

        # Tạo bản ghi trạng thái ban đầu
        record = InterviewRecord(
            batch_id=batch_id,
            candidate_name=candidate_name,
            candidate_profile=candidate_profile,
            candidate_context=candidate_context,
            classified_level=classified_level,
            current_difficulty=initial_difficulty,
            current_phase=InterviewPhase.WARMUP,
            attempts_at_current_level=0,
            total_questions_asked=0,
            upper_level_reached=0,
            warmup_questions_asked=0,
            history=[],
            conversation_memory=[],
            is_finished=False
        )

        # ✅ Tạo câu hỏi warm-up đầu tiên (nhận Dict)
        warmup_data = self.warmup_manager.generate_warmup_question(
            candidate_name=candidate_name.split(',')[0],
            candidate_context=candidate_context,
            topic=context.topic,
            warmup_count=0
        )

        # ✅ Thêm câu hỏi vào history với time_limit
        record.history.append(QuestionAttempt(
            question=warmup_data["question"],
            answer="",
            score=0.0,
            analysis="(warmup - không chấm điểm)",
            difficulty=QuestionDifficulty.VERY_EASY,
            timestamp=datetime.datetime.now().isoformat(),
            question_hash=calculate_question_hash(warmup_data["question"]),
            time_limit=warmup_data["time_limit"]  # ✅ THÊM
        ))

        # ✅ Trả về dict thay vì chỉ string
        return record, warmup_data

    def process_answer(
            self,
            record: InterviewRecord,
            context: InterviewContext,
            answer: str,
            time_spent: int = 0  # ✅ THÊM: thời gian thí sinh đã dùng (giây)
    ) -> Tuple[InterviewRecord, Dict]:
        """
        Xử lý câu trả lời của thí sinh, cập nhật bản ghi và tạo câu hỏi tiếp theo.

        Args:
            record: Bản ghi phỏng vấn hiện tại
            context: Context của batch
            answer: Câu trả lời của thí sinh
            time_spent: Thời gian thí sinh đã dùng (giây)

        Returns:
            - InterviewRecord: Bản ghi trạng thái đã được cập nhật.
            - Dict: Kết quả để trả về cho API (chứa câu hỏi tiếp theo, điểm, time_limit, etc.).
        """
        if record.is_finished:
            summary = self._generate_summary(record, context)
            return record, {"finished": True, "summary": summary}

        # ✅ Cập nhật time_spent vào attempt cuối cùng
        if record.history:
            record.history[-1].time_spent = time_spent

        if record.current_phase == InterviewPhase.WARMUP:
            return self._handle_warmup_answer(record, context, answer)
        elif record.current_phase == InterviewPhase.TECHNICAL:
            return self._handle_technical_answer(record, context, answer)
        else:  # Closing
            summary = self._generate_summary(record, context)
            record.is_finished = True
            return record, {"finished": True, "summary": summary}

    def _handle_warmup_answer(
            self,
            record: InterviewRecord,
            context: InterviewContext,
            answer: str
    ) -> Tuple[InterviewRecord, Dict]:
        """Xử lý câu trả lời trong giai đoạn warm-up."""
        config = context.config

        # Cập nhật câu trả lời vào attempt cuối cùng
        last_attempt = record.history[-1]
        last_attempt.answer = answer
        last_attempt.analysis = "✅ Cảm ơn bạn đã chia sẻ!"

        # Cập nhật memory
        memory = ConversationMemory(record.conversation_memory, config.max_memory_turns)
        memory.add("student", answer)
        memory.add("interviewer", "Cảm ơn bạn!")
        record.conversation_memory = memory.get_history()

        record.warmup_questions_asked += 1

        if record.warmup_questions_asked >= config.max_warmup_questions:
            # ✅ Chuyển sang giai đoạn technical
            record.current_phase = InterviewPhase.TECHNICAL

            # ✅ Nhận Dict thay vì str
            next_q_data = self.question_generator.generate_with_context(
                context.topic, record.current_difficulty, context.knowledge_text,
                memory, record.candidate_context, context.outline_summary
            )

            api_result = {
                "finished": False,
                "score": 0,
                "analysis": "✅ Phần làm quen hoàn tất! Bây giờ chúng ta bắt đầu phần chuyên môn nhé.",
                "next_question": next_q_data["question"],  # ✅
                "difficulty": next_q_data["difficulty"],  # ✅
                "time_limit": next_q_data["time_limit"],  # ✅ THÊM
                "phase": "technical"
            }

            # ✅ Thêm câu hỏi mới vào history với time_limit
            record.history.append(QuestionAttempt(
                question=next_q_data["question"],
                answer="",
                score=0.0,
                analysis="(pending)",
                difficulty=record.current_difficulty,
                timestamp=datetime.datetime.now().isoformat(),
                question_hash=calculate_question_hash(next_q_data["question"]),
                time_limit=next_q_data["time_limit"]  # ✅
            ))
        else:
            # ✅ Hỏi câu warm-up tiếp theo (nhận Dict)
            warmup_data = self.warmup_manager.generate_warmup_question(
                record.candidate_name.split(',')[0],
                record.candidate_context,
                context.topic,
                record.warmup_questions_asked
            )

            api_result = {
                "finished": False,
                "score": 0,
                "analysis": "✅ Tuyệt vời!",
                "next_question": warmup_data["question"],  # ✅
                "difficulty": warmup_data["difficulty"],  # ✅
                "time_limit": warmup_data["time_limit"],  # ✅ THÊM
                "phase": "warmup"
            }

            # ✅ Thêm câu hỏi mới vào history với time_limit
            record.history.append(QuestionAttempt(
                question=warmup_data["question"],
                answer="",
                score=0.0,
                analysis="(pending)",
                difficulty=record.current_difficulty,
                timestamp=datetime.datetime.now().isoformat(),
                question_hash=calculate_question_hash(warmup_data["question"]),
                time_limit=warmup_data["time_limit"]  # ✅
            ))

        return record, api_result

    def _handle_technical_answer(
            self,
            record: InterviewRecord,
            context: InterviewContext,
            answer: str
    ) -> Tuple[InterviewRecord, Dict]:
        """Xử lý câu trả lời trong giai đoạn technical."""
        config = context.config
        last_attempt = record.history[-1]
        memory = ConversationMemory(record.conversation_memory, config.max_memory_turns)

        # Chấm điểm
        score, analysis = self.answer_evaluator.evaluate(
            last_attempt.question,
            answer,
            context.knowledge_text
        )
        print("Thời gian đánh giá xong:", datetime.datetime.now().isoformat())

        # Cập nhật attempt và memory
        last_attempt.answer = answer
        last_attempt.score = score
        last_attempt.analysis = analysis
        memory.add("student", answer)
        memory.add("interviewer", f"📊 Điểm: {score}/10 - {analysis}")
        record.conversation_memory = memory.get_history()

        # Cập nhật trạng thái tổng thể của record
        self._update_record_state(record, score, config)

        # Kiểm tra kết thúc
        if record.is_finished:
            summary = self._generate_summary(record, context)
            return record, {"finished": True, "summary": summary}

        # ✅ Tạo câu hỏi tiếp theo (nhận Dict)
        next_q_data = self.question_generator.generate_with_context(
            context.topic,
            record.current_difficulty,
            context.knowledge_text,
            memory,
            record.candidate_context,
            context.outline_summary
        )
        print(f"Thời gian tạo câu hỏi kỹ thuật tiếp theo xong:", datetime.datetime.now().isoformat())

        # ✅ Thêm câu hỏi mới vào history với time_limit
        record.history.append(QuestionAttempt(
            question=next_q_data["question"],
            answer="",
            score=0.0,
            analysis="(pending)",
            difficulty=record.current_difficulty,
            timestamp=datetime.datetime.now().isoformat(),
            question_hash=calculate_question_hash(next_q_data["question"]),
            time_limit=next_q_data["time_limit"]  # ✅
        ))

        api_result = {
            "finished": False,
            "score": score,
            "analysis": analysis,
            "next_question": next_q_data["question"],  # ✅
            "difficulty": next_q_data["difficulty"],  # ✅
            "time_limit": next_q_data["time_limit"],  # ✅ THÊM
            "phase": "technical"
        }

        return record, api_result

    def _update_record_state(
            self,
            record: InterviewRecord,
            score: float,
            config: InterviewConfig
    ):
        """Update trạng thái của record dựa trên điểm số câu trả lời."""
        record.total_questions_asked += 1
        action = self.difficulty_adapter.decide_next_action(score, config)

        if action == "harder":
            record.upper_level_reached += 1
            if record.upper_level_reached <= config.max_upper_level:
                record.current_difficulty = self.difficulty_adapter.get_next_difficulty(
                    record.current_difficulty, "harder"
                )
                record.attempts_at_current_level = 0
            else:
                record.is_finished = True

        elif action == "same":
            record.attempts_at_current_level += 1

        else:  # easier
            record.current_difficulty = self.difficulty_adapter.get_next_difficulty(
                record.current_difficulty, "easier"
            )
            record.attempts_at_current_level += 1
            record.upper_level_reached = max(0, record.upper_level_reached - 1)

        # Kiểm tra điều kiện kết thúc
        if (record.attempts_at_current_level >= config.max_attempts_per_level or
                record.total_questions_asked >= config.max_total_questions):
            record.is_finished = True

        # Tính điểm cuối cùng nếu đã kết thúc
        if record.is_finished:
            # Chỉ tính điểm từ các câu technical (bỏ warmup)
            technical_scores = [
                attempt.score
                for attempt in record.history
                if attempt.score > 0 and "warmup" not in attempt.analysis.lower()
            ]
            record.final_score = sum(technical_scores) / len(technical_scores) if technical_scores else 0.0

    def _generate_summary(
            self,
            record: InterviewRecord,
            context: InterviewContext
    ) -> Dict:
        """Tạo bản tóm tắt cuối cùng của buổi phỏng vấn."""

        # Convert QuestionAttempt objects to dicts
        history_dicts = []
        for i, attempt in enumerate(record.history, 1):
            attempt_dict = asdict(attempt)

            # Convert Enum to string
            if isinstance(attempt_dict['difficulty'], QuestionDifficulty):
                attempt_dict['difficulty'] = attempt_dict['difficulty'].value
            elif hasattr(attempt_dict['difficulty'], 'value'):
                attempt_dict['difficulty'] = attempt_dict['difficulty'].value

            # Add question number
            attempt_dict['question_number'] = i
            history_dicts.append(attempt_dict)

        return {
            "candidate_info": {
                "name": record.candidate_name,
                "profile": record.candidate_profile,
                "classified_level": record.classified_level.value
            },
            "interview_stats": {
                "timestamp": datetime.datetime.now().isoformat(),
                "total_questions": len(record.history),
                "final_score": record.final_score,
                "topic": context.topic,
                "outline": context.outline
            },
            "question_history": history_dicts
        }

