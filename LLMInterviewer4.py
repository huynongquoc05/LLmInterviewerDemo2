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
    ) -> str:
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

        return parsed.get("question", f"Xin chào {candidate_name}! Bạn đã sẵn sàng cho buổi phỏng vấn chưa?")

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

    def generate_with_context(
            self,
            topic: str,
            difficulty: QuestionDifficulty,
            knowledge_text: str,
            memory: ConversationMemory,
            candidate_context: str,
            outline_summary: str = ""
    ) -> str:
        """Generate câu hỏi có nhận thức về thí sinh."""

        difficulty_descriptions = {
            QuestionDifficulty.VERY_EASY: "rất cơ bản — kiểm tra khái niệm, định nghĩa.",
            QuestionDifficulty.EASY: "cơ bản — yêu cầu giải thích khái niệm hoặc ví dụ đơn giản.",
            QuestionDifficulty.MEDIUM: "trung cấp — ứng dụng thực tế, kết hợp 1—2 khái niệm.",
            QuestionDifficulty.HARD: "nâng cao — yêu cầu phân tích sâu hoặc thiết kế nhỏ.",
            QuestionDifficulty.VERY_HARD: "rất khó — yêu cầu tổng hợp, thiết kế hệ thống."
        }

        history_text = memory.build_prompt()

        prompt = f"""
Bạn là một Interviewer AI THÔNG MINH.

THÔNG TIN THÍ SINH:
{candidate_context}

LỊCH SỬ HỘI THOẠI:
{history_text}

Hãy tạo câu hỏi về "{topic}" với độ khó: {difficulty_descriptions[difficulty]}

TÀI LIỆU THAM KHẢO:
{knowledge_text[:2000] if knowledge_text else "Không có tài liệu"}

TÓM TẮT TÀI LIỆU:
{outline_summary or "Không có"}

YÊU CẦU:
- Câu hỏi CÁ NHÂN HÓA, phù hợp với level của thí sinh
- Nếu thí sinh yếu, hỏi lại theo cách khác. Nếu giỏi, đẩy khó hơn
- Tránh lặp lại câu hỏi tương tự trong lịch sử
- Nếu thí sinh trả lời tốt câu trước, dành 1 lời khen trước câu hỏi mới
- Code example dùng <pre><code class='language-java'>...</code></pre>
- Dùng <br> để xuống dòng cho dễ đọc

OUTPUT: JSON
{{"question": "lời khen (nếu có) + câu hỏi cá nhân hóa..."}}
"""

        result = self.llm.invoke(prompt)
        parsed = _clean_and_parse_json_response(result)
        question = parsed.get("question", "Bạn có thể giải thích thêm được không?")

        # Format question: giữ nguyên code blocks
        question = re.sub(
            r"<pre><code([^>]*)>([\s\S]*?)</code></pre>",
            lambda m: f"<pre><code{m.group(1)}>{m.group(2).replace('<br>', '\n')}</code></pre>",
            question
        )

        return question


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
        """Đánh giá câu trả lời."""

        prompt = f"""
Bạn là giám khảo phỏng vấn, chấm điểm dựa trên tài liệu tham khảo.

CÂU HỎI:
{question}

CÂU TRẢ LỜI:
{answer}

TÀI LIỆU THAM KHẢO:
{knowledge_text[:2000] if knowledge_text else "Không có tài liệu"}

HÃY ĐÁNH GIÁ VÀ CHẤM ĐIỂM:
1️⃣ Phân tích ý chính của câu trả lời
2️⃣ Đối chiếu từng ý với tài liệu:
   ✅ "Khớp" → 8-10 điểm
   ⚙️ "Đúng ngoài tài liệu" → 6-8 điểm
   ❌ "Sai" → 0-4 điểm
3️⃣ Tổng hợp điểm: Nếu không đủ tài liệu để đánh giá → 5 điểm

TRẢ VỀ JSON:
{{
  "score": <float 0-10>,
  "analysis": "<phân tích ngắn gọn>"
}}
"""

        try:
            result = self.llm.invoke(prompt)
            parsed = _parse_evaluation_response(result)

            score = float(parsed.get("score", 5.0))
            analysis = parsed.get("analysis", "Không có nhận xét")

            return score, analysis

        except Exception as e:
            print(f"Lỗi khi chấm điểm: {e}")
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
    ) -> Tuple[InterviewRecord, str]:
        """
        Khởi tạo một bản ghi phỏng vấn mới cho thí sinh.

        Returns:
            - InterviewRecord: Đối tượng bản ghi trạng thái ban đầu.
            - str: Câu hỏi warm-up đầu tiên.
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

        # Tạo câu hỏi warm-up đầu tiên
        first_question = self.warmup_manager.generate_warmup_question(
            candidate_name=candidate_name.split(',')[0],
            candidate_context=candidate_context,
            topic=context.topic,
            warmup_count=0
        )

        # Thêm câu hỏi vào history (chưa có câu trả lời)
        record.history.append(QuestionAttempt(
            question=first_question,
            answer="",
            score=0.0,
            analysis="(warmup - không chấm điểm)",
            difficulty=QuestionDifficulty.VERY_EASY,
            timestamp=datetime.datetime.now().isoformat(),
            question_hash=calculate_question_hash(first_question)
        ))

        return record, first_question

    def process_answer(
            self,
            record: InterviewRecord,
            context: InterviewContext,
            answer: str
    ) -> Tuple[InterviewRecord, Dict]:
        """
        Xử lý câu trả lời của thí sinh, cập nhật bản ghi và tạo câu hỏi tiếp theo.

        Returns:
            - InterviewRecord: Bản ghi trạng thái đã được cập nhật.
            - Dict: Kết quả để trả về cho API (chứa câu hỏi tiếp theo, điểm, etc.).
        """
        if record.is_finished:
            summary = self._generate_summary(record, context)
            return record, {"finished": True, "summary": summary}

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
            # Chuyển sang giai đoạn technical
            record.current_phase = InterviewPhase.TECHNICAL
            next_question = self.question_generator.generate_with_context(
                context.topic, record.current_difficulty, context.knowledge_text,
                memory, record.candidate_context, context.outline_summary
            )
            api_result = {
                "finished": False,
                "score": 0,
                "analysis": "✅ Phần làm quen hoàn tất! Bây giờ chúng ta bắt đầu phần chuyên môn nhé.",
                "next_question": next_question,
                "difficulty": record.current_difficulty.value,
                "phase": "technical"
            }
        else:
            # Hỏi câu warm-up tiếp theo
            next_question = self.warmup_manager.generate_warmup_question(
                record.candidate_name.split(',')[0],
                record.candidate_context,
                context.topic,
                record.warmup_questions_asked
            )
            api_result = {
                "finished": False,
                "score": 0,
                "analysis": "✅ Tuyệt vời!",
                "next_question": next_question,
                "difficulty": "warmup",
                "phase": "warmup"
            }

        # Thêm câu hỏi mới vào history
        record.history.append(QuestionAttempt(
            question=next_question,
            answer="",
            score=0.0,
            analysis="(pending)",
            difficulty=record.current_difficulty,
            timestamp=datetime.datetime.now().isoformat(),
            question_hash=calculate_question_hash(next_question)
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
        print("Thời gian đan gi xong:", datetime.datetime.now().isoformat())

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

        # Tạo câu hỏi tiếp theo
        next_question = self.question_generator.generate_with_context(
            context.topic,
            record.current_difficulty,
            context.knowledge_text,
            memory,
            record.candidate_context,
            context.outline_summary
        )
        print(f"Thời gian tạo câu hỏi kỹ thuật tiếp theo xong:", datetime.datetime.now().isoformat())

        record.history.append(QuestionAttempt(
            question=next_question,
            answer="",
            score=0.0,
            analysis="(pending)",
            difficulty=record.current_difficulty,
            timestamp=datetime.datetime.now().isoformat(),
            question_hash=calculate_question_hash(next_question)
        ))

        api_result = {
            "finished": False,
            "score": score,
            "analysis": analysis,
            "next_question": next_question,
            "difficulty": record.current_difficulty.value,
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


# # =======================
# # 6. USAGE EXAMPLE (Optional)
# # =======================
#
# if __name__ == "__main__":
#     """
#     Example usage - chỉ để test logic, không dùng trong production
#     """
#     from langchain_google_genai import GoogleGenerativeAI
#
#     # Mock LLM
#     llm = GoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.5)
#
#     # Create processor
#     processor = InterviewProcessor(llm=llm)
#
#     # Mock context
#     context = InterviewContext(
#         topic="Kiểu dữ liệu trong Java",
#         outline=["Kiểu dữ liệu cơ sở", "String", "Array"],
#         knowledge_text="Java có 8 kiểu dữ liệu nguyên thủy...",
#         outline_summary="Tài liệu đầy đủ về kiểu dữ liệu",
#         config=InterviewConfig()
#     )
#
#     # Start interview
#     record, first_question = processor.start_new_record(
#         batch_id="test_batch_123",
#         candidate_name="Nguyễn Văn A,K65",
#         candidate_profile="Tên: Nguyễn Văn A\nLớp: K65\nĐiểm 40%: 7.5",
#         classified_level=Level.KHA,
#         context=context
#     )
#
#     print("=" * 60)
#     print("🎯 STARTED NEW INTERVIEW RECORD")
#     print("=" * 60)
#     print(f"Candidate: {record.candidate_name}")
#     print(f"Level: {record.classified_level.value}")
#     print(f"Phase: {record.current_phase.value}")
#     print(f"First Question: {first_question}")
#     print("=" * 60)
#
#     # Simulate answer
#     test_answer = "Tôi rất thích học Java vì nó rất phổ biến"
#
#     updated_record, result = processor.process_answer(record, context, test_answer)
#
#     print("\n🔄 PROCESSED ANSWER")
#     print("=" * 60)
#     print(f"Answer: {test_answer}")
#     print(f"Finished: {result.get('finished')}")
#     print(f"Next Phase: {result.get('phase')}")
#     if 'next_question' in result:
#         print(f"Next Question: {result['next_question'][:100]}...")
#     print("=" * 60)