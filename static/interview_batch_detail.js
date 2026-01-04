// ==================== GLOBAL STATE ====================
const STATE = {
    sessionId: null,
    sessionData: null,
    currentCandidate: null,
    currentQuestion: "",
    currentAudio: null,
    autoPlayEnabled: true,
    currentRecordId: null,
    basePath: window.location.pathname.startsWith('/iview1') ? '/iview1' : '',

    // ✅ TIMER STATE
    timeLimit: 0,           // Thời gian cho phép (giây)
    timeRemaining: 0,       // Thời gian còn lại (giây)
    startTime: null,        // Thời điểm bắt đầu
    timerInterval: null,    // Interval ID

    // ✅ VOICE STATE
    recognition: null,
    isRecording: false
};

// ==================== API CALLS ====================
const API = {
    async fetchSession(sessionId) {
        const response = await fetch(`${STATE.basePath}/interview_batch/get/${sessionId}`);
        return await response.json();
    },

async startInterview(sessionId, candidateName) {
        const response = await fetch(`${STATE.basePath}/interview/start_candidate`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: sessionId,
                candidate_name: candidateName
            })
        });

        if (response.status === 401) {
            alert('Vui lòng đăng nhập lại');
            window.location.href = `${STATE.basePath}/login`;
            return null;
        }
        if (response.status === 403) {
            alert('Bạn không có quyền truy cập batch này!');
            window.location.href = `${STATE.basePath}/interview_batch`;
            return null;
        }

        return await response.json();
    }, // <--- Giữ dấu phẩy này để ngăn cách với hàm dưới



    async submitAnswer(recordId, candidate, answer, timeSpent) {
        const response = await fetch(`${STATE.basePath}/interview/answer`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                record_id: recordId,
                candidate,
                answer,
                time_spent: timeSpent  // ✅ THÊM
            })
        });

        if (response.status === 401) {
            alert('Vui lòng đăng nhập lại');
            window.location.href = `${STATE.basePath}/login`;
            return null;
        }
        if (response.status === 403) {
            alert('Bạn không có quyền truy cập!');
            return null;
        }

        return await response.json();
    },

    async updateCandidateStatus(sessionId, candidateName, status) {
        await fetch(`${STATE.basePath}/interview_batch/update_candidate_status`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ session_id: sessionId, candidate_name: candidateName, status })
        });
    },

    async deleteSession(sessionId) {
        const response = await fetch(`${STATE.basePath}/interview_batch/delete/${sessionId}`, {
            method: 'DELETE'
        });
        return await response.json();
    }
};

// ==================== TIMER CONTROL ====================
const Timer = {
    start(timeLimit) {
        this.stop(); // Clear previous timer

        STATE.timeLimit = timeLimit;
        STATE.timeRemaining = timeLimit;
        STATE.startTime = Date.now();

        this.updateDisplay();
        document.getElementById('timerDisplay').style.display = 'flex';

        STATE.timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - STATE.startTime) / 1000);
            STATE.timeRemaining = Math.max(0, STATE.timeLimit - elapsed);

            this.updateDisplay();

            // ✅ AUTO-SUBMIT khi hết thời gian
            if (STATE.timeRemaining === 0) {
                this.stop();
                Interview.submitAnswer(true); // true = auto-submit
            }
        }, 1000);
    },
    // ✅ THÊM HÀM MỚI: Chỉ start nếu chưa chạy
    startIfNotRunning() {
        if (!STATE.timerInterval) {
            // Nếu chưa có timeLimit (trường hợp click mic trước khi audio load xong), lấy mặc định
            const limit = STATE.timeLimit || 90;
            this.start(limit);
        }
    },

    // ✅ THÊM HÀM MỚI: Chỉ hiển thị số phút/giây, không đếm ngược
    resetDisplay(timeLimit) {
        this.stop(); // Đảm bảo không chạy ngầm
        STATE.timeLimit = timeLimit;
        STATE.timeRemaining = timeLimit;
        this.updateDisplay();
        document.getElementById('timerDisplay').style.display = 'flex';
    },

    stop() {
        if (STATE.timerInterval) {
            clearInterval(STATE.timerInterval);
            STATE.timerInterval = null;
        }
    },

    hide() {
        this.stop();
        document.getElementById('timerDisplay').style.display = 'none';
    },

    updateDisplay() {
        const minutes = Math.floor(STATE.timeRemaining / 60);
        const seconds = STATE.timeRemaining % 60;
        const timeText = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;

        const timerDisplay = document.getElementById('timerDisplay');
        const timerText = document.getElementById('timerText');
        const timerLabel = document.getElementById('timerLabel');

        timerText.textContent = timeText;

        // ✅ Warning khi còn 30s
        if (STATE.timeRemaining <= 30 && STATE.timeRemaining > 0) {
            timerDisplay.classList.add('warning');
            timerDisplay.classList.remove('expired');
            timerLabel.textContent = '⚠️ Sắp hết giờ!';
        } else if (STATE.timeRemaining === 0) {
            timerDisplay.classList.remove('warning');
            timerDisplay.classList.add('expired');
            timerLabel.textContent = '⏰ Hết giờ!';
        } else {
            timerDisplay.classList.remove('warning', 'expired');
            timerLabel.textContent = `Thời gian trả lời`;
        }
    },

    getTimeSpent() {
        if (!STATE.startTime) return 0;
        return Math.floor((Date.now() - STATE.startTime) / 1000);
    }
};

// ==================== VOICE RECOGNITION ====================
const Voice = {
    init() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

        if (!SpeechRecognition) {
            console.warn('Browser không hỗ trợ Web Speech API');
            const voiceBtn = document.getElementById('voiceBtn');
            if (voiceBtn) {
                voiceBtn.disabled = true;
                voiceBtn.innerHTML = '<i class="fas fa-microphone-slash"></i> Không hỗ trợ';
            }
            return false;
        }

        STATE.recognition = new SpeechRecognition();
        STATE.recognition.lang = 'vi-VN';
        STATE.recognition.interimResults = true;
        STATE.recognition.continuous = true;

        STATE.recognition.onresult = (event) => {
            let transcript = '';
            for (let i = 0; i < event.results.length; i++) {
                transcript += event.results[i][0].transcript;
            }

            const textarea = document.getElementById('answerTextarea');
            if (textarea) {
                textarea.value = transcript;
                // Auto-expand
                textarea.style.height = 'auto';
                textarea.style.height = (textarea.scrollHeight) + 'px';
            }
        };

        STATE.recognition.onerror = (event) => {
            console.error('Voice recognition error:', event.error);
            this.stop();

            if (event.error === 'no-speech') {
                alert('⚠️ Không nghe thấy giọng nói. Vui lòng thử lại!');
            } else if (event.error === 'not-allowed') {
                alert('⚠️ Bạn cần cấp quyền microphone cho trình duyệt!');
            }
        };

        STATE.recognition.onend = () => {
            if (STATE.isRecording) {
                // Restart nếu đang trong chế độ recording
                STATE.recognition.start();
            }
        };

        return true;
    },

    toggle() {
        if (!STATE.recognition && !this.init()) {
            return;
        }

        if (STATE.isRecording) {
            this.stop();
        } else {
            this.start();
        }
    },

    start() {
            try {
                STATE.recognition.start();
                STATE.isRecording = true;

                // ✅ THÊM: Bắt đầu nói là bắt đầu tính giờ (nếu chưa tính)
                Timer.startIfNotRunning();

                // ✅ THÊM: Nếu đang phát audio thì dừng audio lại
                if (STATE.currentAudio && !STATE.currentAudio.paused) {
                    Audio.stop(); // Hàm này đã bao gồm Timer.startIfNotRunning() nên rất an toàn
                }

                const voiceBtn = document.getElementById('voiceBtn');
                if (voiceBtn) {
                    voiceBtn.classList.add('recording');
                    voiceBtn.innerHTML = '<i class="fas fa-stop"></i> Dừng nói';
                }
            } catch (error) {
                console.error('Cannot start voice recognition:', error);
            }
        },

    stop() {
        if (STATE.recognition) {
            STATE.recognition.stop();
        }
        STATE.isRecording = false;

        const voiceBtn = document.getElementById('voiceBtn');
        if (voiceBtn) {
            voiceBtn.classList.remove('recording');
            voiceBtn.innerHTML = '<i class="fas fa-microphone"></i> Nói';
        }
    }
};

// ==================== UI UPDATES ====================
const UI = {
    showLoading(show, message = 'Đang xử lý...') {
        const overlay = document.getElementById('loadingOverlay');
        const text = overlay?.querySelector('.loading-text');
        if (overlay) overlay.style.display = show ? 'flex' : 'none';
        if (text) text.textContent = message;
    },
        // ✅ THÊM: Hiển thị lời kết thúc
    showClosingMessage(closingMessage, onContinue) {
        document.getElementById('questionSection').style.display = 'none';
        document.getElementById('answerSection').style.display = 'none';
        Timer.hide();

        const closingHTML = `
            <div class="closing-message-container">
                <div class="closing-icon">
                    <i class="fas fa-check-circle"></i>
                </div>
                <div class="closing-text">
                    ${closingMessage}
                </div>
                <button class="btn btn-primary btn-lg" onclick="window.closingContinue()" style="margin-top: 20px;">
                    <i class="fas fa-arrow-right"></i> Xem báo cáo chi tiết
                </button>
            </div>
        `;

        document.getElementById('resultSection').innerHTML = closingHTML;
        document.getElementById('resultSection').style.display = 'block';

        // Lưu callback để gọi khi nhấn nút
        window.closingContinue = onContinue;
    },


displaySessionInfo(data) {
        // 1. Các thông tin cơ bản
        document.getElementById('sessionName').textContent = data.session_name;
        document.getElementById('topicName').textContent = data.topic;
        document.getElementById('totalCandidates').textContent = data.total_count;
        document.getElementById('completedCandidates').textContent = data.completed_count;

        const progressPercent = data.total_count > 0 ? (data.completed_count / data.total_count) * 100 : 0;
        document.getElementById('progressPercent').textContent = Math.round(progressPercent) + '%';

        // 2. ✅ VIỆT HÓA CONFIG (Đã cập nhật theo yêu cầu của bạn)
        const config = data.config;
        const configMapping = {
            threshold_high: "Điểm tăng độ khó (>=)",
            threshold_low: "Điểm giảm độ khó (<=)",
            max_total_questions: "Số câu hỏi tối đa",
            max_upper_level: "Giới hạn số lần nâng độ khó",
//            llm_temperature: "Độ sáng tạo (Temperature)",
            // Các dòng dưới đã được comment theo yêu cầu
            // max_memory_turns: "Bộ nhớ ngữ cảnh (Turns)",
            // max_attempts_per_level: "Số lần thử lại mức độ"
        };

        let configHtml = '';
        for (const [key, value] of Object.entries(config)) {
            // Chỉ hiển thị những key có trong mapping
            if (configMapping[key]) {
                const label = configMapping[key];
                configHtml += `
                    <div style="margin-bottom: 8px; display: flex; justify-content: space-between; border-bottom: 1px dashed #e2e8f0; padding-bottom: 4px;">
                        <span style="color: #4a5568;">${label}:</span>
                        <span style="font-weight: 600; color: #2d3748;">${value}</span>
                    </div>`;
            }
        }
        document.getElementById('configInfo').innerHTML = configHtml;

        // 3. ✅ OUTLINE & VECTORSTORE PATH
        let outlineHtml = '';

        // Hiển thị Outline dạng list
        if (data.outline && data.outline.length > 0) {
            outlineHtml += '<ul style="padding-left: 20px; margin-top: 0;">';
            data.outline.forEach(item => {
                outlineHtml += `<li style="margin-bottom: 5px;">${item}</li>`;
            });
            outlineHtml += '</ul>';
        } else {
            outlineHtml += '<p>Không có outline</p>';
        }

        // Hiển thị Vectorstore Path
        if (data.knowledge_vectorstore_path) {
            outlineHtml += `
                <div style="margin-top: 15px; padding-top: 10px; border-top: 1px solid #eee;">
                    <div style="font-size: 12px; color: #718096; font-weight: bold; margin-bottom: 5px;">
                        <i class="fas fa-database"></i> Đường dẫn Vectorstore:
                    </div>
                    <code style="display: block; background: #f1f5f9; padding: 8px; border-radius: 4px; font-size: 11px; word-break: break-all; color: #4a5568;">
                        ${data.knowledge_vectorstore_path}
                    </code>
                </div>
            `;
        }
        document.getElementById('outlineInfo').innerHTML = outlineHtml;

        // 4. ✅ Knowledge Text (Đã bỏ Summary)
        const knowledgeTextElem = document.getElementById('knowledgeText');
        if (knowledgeTextElem) {
            knowledgeTextElem.textContent = data.knowledge_text || "Không có nội dung chi tiết.";
        }
    },

    displayCandidates(candidates) {
        const container = document.getElementById('candidatesGrid');
        if (!candidates?.length) {
            container.innerHTML = '<p style="text-align:center; color:#718096;">Chưa có thí sinh nào</p>';
            return;
        }

        const statusText = {
            'pending': 'Chưa phỏng vấn',
            'in_progress': 'Đang phỏng vấn',
            'completed': 'Đã hoàn thành'
        };

        const columns = Object.keys(candidates[0]);
        container.innerHTML = candidates.map((candidate, idx) => {
            const status = candidate.status || 'pending';
            const details = columns
                .filter(col => col !== 'status')
                .map(col => `<strong>${col}</strong>: ${candidate[col]}`)
                .join('<br>');

            return `
                <div class="candidate-card ${status}" data-index="${idx}">
                    <span class="status-badge status-${status}">${statusText[status]}</span>
                    <div class="candidate-details">${details}</div>
                </div>
            `;
        }).join('');

        // Event listeners
        document.querySelectorAll('.candidate-card').forEach(card => {
            card.addEventListener('click', () => {
                const idx = card.getAttribute('data-index');
                Interview.startFromCandidate(candidates[idx]);
            });
        });
    },

    showModal(show) {
        const modal = document.getElementById('interviewModal');
        if (modal) modal.classList.toggle('active', show);
    },

    updateModalContent(candidateName, question, difficulty, timeLimit, isResume = false) {  // ✅ Bỏ candidateClass
        document.getElementById('modalCandidateName').textContent = candidateName;  // ✅ Chỉ hiển thị tên

        let questionHTML = `<i class="fas fa-robot"></i> ${question}`;
        if (isResume) {
            questionHTML = `
                <div class="alert alert-info" style="margin-bottom: 15px;">
                    <i class="fas fa-info-circle"></i>
                    <strong>Tiếp tục phỏng vấn:</strong> Bắt đầu lại từ đầu do phiên trước chưa hoàn thành.
                </div>
                ${questionHTML}
            `;
        }

        const difficultyBadge = `
            <div class="difficulty-badge difficulty-${difficulty}" style="display: inline-block; margin-left: 10px; padding: 4px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;">
                ${difficulty.replace('_', ' ').toUpperCase()}
            </div>
        `;

        document.getElementById('modalQuestion').innerHTML = questionHTML + difficultyBadge;
        if (window.Prism) Prism.highlightAll();

        document.getElementById('answerTextarea').value = '';
        document.getElementById('resultSection').style.display = 'none';
        document.getElementById('questionSection').style.display = 'block';
        document.getElementById('answerSection').style.display = 'block';
        document.getElementById('finishBtn').style.display = 'none';

//        Timer.start(timeLimit);
        Timer.resetDisplay(timeLimit);
    },

    showCompletedSummary(summary) {
        document.getElementById('modalCandidateName').textContent = summary.candidate_info.name;
        document.getElementById('questionSection').style.display = 'none';
        document.getElementById('answerSection').style.display = 'none';
        Timer.hide();

        const summaryHTML = HTML.generateSummary(summary);
        document.getElementById('resultSection').innerHTML = summaryHTML;
        document.getElementById('resultSection').style.display = 'block';

        const finishBtn = document.getElementById('finishBtn');
        finishBtn.style.display = 'inline-block';
        finishBtn.innerHTML = '<i class="fas fa-times"></i> Đóng';
        finishBtn.onclick = () => {
            UI.showModal(false);
            Audio.stop();
            Audio.hideControls();
            Timer.hide();
        };

        this.addRestartButton();
        UI.showModal(true);
    },

    addRestartButton() {
        const buttonContainer = document.querySelector('#resultSection')
            .closest('.modal-body')
            .querySelector('div[style*="text-align: center"]');

        if (buttonContainer.querySelector('.btn-warning')) return;

        const restartBtn = document.createElement('button');
        restartBtn.className = 'btn btn-warning';
        restartBtn.style.marginLeft = '10px';
        restartBtn.innerHTML = '<i class="fas fa-redo"></i> Phỏng vấn lại';
        restartBtn.onclick = () => {
            if (!confirm('⚠️ Bạn có chắc muốn phỏng vấn lại? Kết quả cũ sẽ bị xóa!')) return;

            UI.showModal(false);
            Audio.stop();
            Audio.hideControls();
            Timer.hide();

            API.updateCandidateStatus(STATE.sessionId, STATE.currentCandidate.name, 'pending')
                .then(() => {
                    loadSessionDetail();
                    setTimeout(() => {
                        Interview.start(STATE.currentCandidate.name, STATE.currentCandidate.class);
                    }, 500);
                });
        };

        buttonContainer.insertBefore(restartBtn, document.getElementById('finishBtn'));
    },

    showScore(score, analysis) {
        const scoreHTML = HTML.generateScore(score, analysis);
                document.getElementById('resultSection').innerHTML = scoreHTML;
                document.getElementById('resultSection').style.display = 'block';
                setTimeout(() => {
                    document.getElementById('resultSection').style.display = 'none';
                }, 3000);
            }
        };

// ==================== HTML GENERATORS (PHIÊN BẢN NÂNG CẤP) ====================
const HTML = {
    /**
     * Nâng cấp: Hiển thị điểm và phân tích (kiểu "chấm điểm" tạm thời)
     */
    generateScore(score, analysis) {
        const scoreClass = score >= 7 ? 'score-good' : score >= 4 ? 'score-average' : 'score-poor';
        return `
            <div class="score-result">
                <div class="score-number ${scoreClass}">${score}/10</div>
                <div class="score-analysis">
                    <i class="fas fa-comment-alt"></i> ${analysis}
                </div>
            </div>
        `;
    },

    /**
     * Nâng cấp: Hiển thị báo cáo kết quả cuối cùng (layout mới)
     */
    generateSummary(summary) {
        const finalScore = summary.interview_stats?.final_score || 0;
        const scoreClass = finalScore >= 7 ? 'score-good' : finalScore >= 4 ? 'score-average' : 'score-poor';

        const historyHTML = summary.question_history?.map(q => {
            const timeSpent = q.time_spent || 0;
            const timeLimit = q.time_limit || 0;
            const timeStatus = timeSpent > timeLimit ? '⏰ Quá giờ' : timeSpent > timeLimit * 0.8 ? '⚠️ Gần hết giờ' : '✅ Đúng giờ';

            // Đảm bảo q.difficulty là string, ví dụ 'medium'
            const difficulty = String(q.difficulty || 'medium').toLowerCase();

            return `
                <div class="question-history-item">
                    <div class="q-header">
                        <h4><i class="fas fa-question-circle"></i> Câu ${q.question_number}</h4>
                        <div class="difficulty-badge difficulty-${difficulty}">${difficulty.replace('_', ' ').toUpperCase()}</div>
                    </div>

                    <div class="q-body">
                        <p class="question-text">${q.question}</p>
                        <p class="answer-text"><strong>Trả lời:</strong> ${q.answer}</p>
                        <div class="question-score">
                            <span class="score-badge">${q.score}/10</span>
                            <span class="analysis-text">${q.analysis}</span>
                        </div>
                    </div>

                    <div class="q-footer">
                        <i class="fas fa-clock"></i>
                        Thời gian: ${timeSpent}s / ${timeLimit}s (${timeStatus})
                    </div>
                </div>
            `;
        }).join('') || '';

        return `
            <div class="interview-summary">
                <div class="summary-header">
                    <h3><i class="fas fa-trophy"></i> Kết quả cuối cùng</h3>
                    <div class="summary-stats">
                        <div class="stat-item">
                            <span class="stat-label">Tổng câu hỏi:</span>
                            <span class="stat-value">${summary.interview_stats?.total_questions || 0}</span>
                        </div>
                        </div>
                    <div class="final-score ${scoreClass}">${finalScore.toFixed(1)}</div>
                </div>

                <div class="question-history">
                    <h4><i class="fas fa-history"></i> Lịch sử câu hỏi</h4>
                    ${historyHTML}
                </div>
            </div>
        `;
    }
};

// ==================== AUDIO CONTROL ====================
const Audio = {
play(audioUrl) {
        if (!audioUrl || !STATE.autoPlayEnabled) return;

        try {
            if (STATE.currentAudio) {
                STATE.currentAudio.pause();
                STATE.currentAudio = null;
            }

            STATE.currentAudio = new window.Audio(audioUrl);
            STATE.currentAudio.volume = 0.8;

            STATE.currentAudio.addEventListener('canplay', () => this.updateStatus('ready'));
            STATE.currentAudio.addEventListener('play', () => this.updateStatus('playing'));
            STATE.currentAudio.addEventListener('pause', () => this.updateStatus('paused'));

            // ✅ SỬA: Khi audio chạy hết -> Bắt đầu tính giờ
            STATE.currentAudio.addEventListener('ended', () => {
                this.updateStatus('ended');
                Timer.startIfNotRunning(); // <--- Thêm dòng này
            });

            STATE.currentAudio.addEventListener('error', () => this.updateStatus('error'));

            STATE.currentAudio.play().catch(() => this.updateStatus('error'));
        } catch (error) {
            console.error('Audio error:', error);
            this.updateStatus('error');
        }
    },

    toggle() {
        if (!STATE.currentAudio) return;
        STATE.currentAudio.paused ? STATE.currentAudio.play() : STATE.currentAudio.pause();
    },

    stop() {
            if (STATE.currentAudio) {
                STATE.currentAudio.pause();
                STATE.currentAudio.currentTime = 0;
                this.updateStatus('stopped');

                // ✅ SỬA: Khi người dùng bấm Stop -> Bắt đầu tính giờ ngay
                Timer.startIfNotRunning();
            }
        },

    toggleAutoPlay() {
        STATE.autoPlayEnabled = !STATE.autoPlayEnabled;
        const btn = document.getElementById('autoPlayBtn');
        if (btn) {
            btn.className = `btn btn-secondary ${STATE.autoPlayEnabled ? 'active' : ''}`;
            btn.innerHTML = `<i class="fas fa-${STATE.autoPlayEnabled ? 'volume-up' : 'volume-mute'}"></i>
                ${STATE.autoPlayEnabled ? 'Tự động phát' : 'Tắt âm thanh'}`;
        }
    },

    updateStatus(status) {
        const statusMap = {
            loading: { icon: 'spinner fa-spin', text: 'Đang tải...', color: '#ed8936' },
            ready: { icon: 'play', text: 'Sẵn sàng', color: '#48bb78' },
            playing: { icon: 'pause', text: 'Đang phát', color: '#4299e1' },
            paused: { icon: 'play', text: 'Tạm dừng', color: '#718096' },
            ended: { icon: 'redo', text: 'Kết thúc', color: '#48bb78' },
            stopped: { icon: 'play', text: 'Đã dừng', color: '#718096' },
            error: { icon: 'exclamation-triangle', text: 'Lỗi', color: '#f56565' }
        };

        const info = statusMap[status] || statusMap.ready;
        const playBtn = document.getElementById('playBtn');
        const audioStatus = document.getElementById('audioStatus');

        if (playBtn) {
            playBtn.innerHTML = `<i class="fas fa-${info.icon}"></i>`;
            playBtn.disabled = status === 'loading';
        }
        if (audioStatus) {
            audioStatus.innerHTML = info.text;
            audioStatus.style.color = info.color;
        }
    },

    showControls(audioUrl) {
        const questionBody = document.querySelector('#questionSection .card-body');
        let existingControls = questionBody?.querySelector('.audio-controls');
        if (existingControls) existingControls.remove();

        const audioControls = document.createElement('div');
        audioControls.className = 'audio-controls';
        audioControls.id = 'audioControls';
        audioControls.innerHTML = `
            <div class="audio-player">
                <button id="playBtn" class="btn-audio" onclick="Audio.toggle()">
                    <i class="fas fa-play"></i>
                </button>
                <button class="btn-audio" onclick="Audio.stop()">
                    <i class="fas fa-stop"></i>
                </button>
                <span id="audioStatus" class="audio-status">Sẵn sàng</span>
            </div>
            <div class="audio-settings">
                <button id="autoPlayBtn" class="btn btn-secondary ${STATE.autoPlayEnabled ? 'active' : ''}"
                    onclick="Audio.toggleAutoPlay()">
                    <i class="fas fa-${STATE.autoPlayEnabled ? 'volume-up' : 'volume-mute'}"></i>
                    ${STATE.autoPlayEnabled ? 'Tự động phát' : 'Tắt âm thanh'}
                </button>
            </div>
        `;

        questionBody?.appendChild(audioControls);
        this.updateStatus('ready');
    },

    hideControls() {
        document.getElementById('audioControls')?.remove();
        this.stop();
    }
};

// ==================== INTERVIEW LOGIC ====================
const Interview = {
    startFromCandidate(candidate) {
        STATE.currentCandidate = candidate;

        // ✅ Chỉ lấy tên (flexible)
        const name = (
            candidate["Họ tên học viên"] ||
            candidate.name ||
            candidate["Tên"] ||
            candidate["Họ tên"] ||
            Object.values(candidate)[0]
        );
        STATE.currentCandidateName = name;

        this.start(name);  // ✅ Không cần class
    },

    async start(candidateName) {  // ✅ Bỏ candidateClass parameter
        UI.showLoading(true, 'Đang kiểm tra trạng thái phỏng vấn...');

        try {
            const data = await API.startInterview(STATE.sessionId, candidateName);  // ✅ Chỉ gửi tên
            if (!data || data.error) throw new Error(data?.error || 'Unknown error');

            if (!data.already_completed) {
                await API.updateCandidateStatus(STATE.sessionId, candidateName, 'in_progress');
                if (STATE.currentCandidate) STATE.currentCandidate.status = 'in_progress';
            }

            STATE.currentRecordId = data.record_id;

            if (data.already_completed) {
                UI.showCompletedSummary(data.summary);
                return;
            }

            STATE.currentQuestion = data.question;
            const timeLimit = data.time_limit || 90;
            const difficulty = data.difficulty || 'medium';

            UI.updateModalContent(
                candidateName,  // ✅ Chỉ hiển thị tên
                data.question,
                difficulty,
                timeLimit,
                data.is_resumed
            );
            UI.showModal(true);

            if (data.audio_url) {
                Audio.showControls(data.audio_url);
                if (STATE.autoPlayEnabled) {
                    setTimeout(() => Audio.play(data.audio_url), 500);
                }
                // Có audio -> Timer đợi sự kiện ended/stop
            } else {
                Audio.hideControls();
                // ✅ THÊM: Không có audio -> Start timer luôn
                Timer.start(timeLimit);
            }

        } catch (error) {
            console.error('Error starting interview:', error);
            alert('Lỗi: ' + error.message);
        } finally {
            UI.showLoading(false);
        }
    },

    async submitAnswer(isAutoSubmit = false) {
        const answer = document.getElementById('answerTextarea').value.trim();

        if (!answer) {
            if (isAutoSubmit) {
                alert('⏰ Hết giờ! Câu trả lời trống sẽ được ghi nhận.');
            } else {
                alert('Vui lòng nhập câu trả lời!');
                return;
            }
        }

        // ✅ Stop voice nếu đang recording
        Voice.stop();

        // ✅ Stop timer và lấy thời gian đã dùng
        const timeSpent = Timer.getTimeSpent();
        Timer.stop();

        Audio.stop();
        UI.showLoading(true, 'Đang chấm điểm...');

        try {
            const fullName = STATE.currentCandidateName || STATE.currentCandidate.name || "Unknown Candidate";

            // ✅ Gửi time_spent lên BE
            const data = await API.submitAnswer(
                STATE.currentRecordId,
                fullName,
                answer || '(Không có câu trả lời)',
                timeSpent
            );

            if (!data || data.error) throw new Error(data?.error || 'Unknown error');

            // ✅ MỚI: Xử lý closing message trước
            if (data.finished) {
                // Cập nhật status
                await API.updateCandidateStatus(STATE.sessionId, STATE.currentCandidate.name, 'completed');
                if (STATE.currentCandidate) STATE.currentCandidate.status = 'completed';

                Audio.hideControls();
                UI.showLoading(false);

                // ✅ Hiển thị lời kết thúc trước
                UI.showClosingMessage(
                    data.closing_message || "Cảm ơn bạn đã tham gia buổi phỏng vấn!",
                    () => {
                        // Callback: Hiển thị summary sau khi nhấn nút
                        UI.showCompletedSummary(data.summary);
                    }
                );

                return; // Dừng ở đây, không show summary ngay
            }

            // ✅ KHÔNG HIỂN THỊ ĐIỂM TẠM THỜI NỮA (bỏ dòng này)
            // UI.showScore(data.score, data.analysis);

            STATE.currentQuestion = data.next_question;

            // ✅ Nhận time_limit và difficulty mới
            const timeLimit = data.time_limit || 90;
            const difficulty = data.difficulty || 'medium';

            // Update question với difficulty badge
            const difficultyBadge = `
                <div class="difficulty-badge difficulty-${difficulty}" style="display: inline-block; margin-left: 10px; padding: 4px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;">
                    ${difficulty.replace('_', ' ').toUpperCase()}
                </div>
            `;

            document.getElementById('modalQuestion').innerHTML =
                `<i class="fas fa-robot"></i> ${data.next_question}` + difficultyBadge;

            if (window.Prism) Prism.highlightAll();
            document.getElementById('answerTextarea').value = '';

            // ✅ Reset timer display (chưa chạy vội)
            Timer.resetDisplay(timeLimit);

            if (data.audio_url) {
                Audio.showControls(data.audio_url);
                if (STATE.autoPlayEnabled) {
                    setTimeout(() => Audio.play(data.audio_url), 1000);
                }
            } else {
                Audio.hideControls();
                // ✅ THÊM: Không có audio -> Start timer luôn
                Timer.start(timeLimit);
            }

        } catch (error) {
            console.error('Error submitting answer:', error);
            alert('Lỗi: ' + error.message);
        } finally {
            UI.showLoading(false);
        }
    },

    // ✅ Kết thúc phỏng vấn sớm
    async endEarly() {
        if (!confirm('⚠️ Bạn có chắc muốn kết thúc phỏng vấn ngay? Kết quả hiện tại sẽ được lưu lại.')) {
            return;
        }

        Timer.stop();
        Voice.stop();
        Audio.stop();

        UI.showLoading(true, 'Đang lưu kết quả...');

        try {
            // ✅ Dùng biến đã chuẩn hóa từ STATE
            const fullName = STATE.currentCandidateName || "Unknown Candidate";
            const answer = document.getElementById('answerTextarea').value.trim() || '(Kết thúc sớm - Không có câu trả lời)';
            const timeSpent = Timer.getTimeSpent();

            const data = await API.submitAnswer(STATE.currentRecordId, fullName, answer, timeSpent);

            if (!data || data.error) throw new Error(data?.error || 'Unknown error');

            // Cập nhật trạng thái completed
            await API.updateCandidateStatus(STATE.sessionId, STATE.currentCandidate.name, 'completed');
            if (STATE.currentCandidate) STATE.currentCandidate.status = 'completed';

            UI.showLoading(false);

            // ✅ MỚI: Hiển thị closing message trước
            if (data.finished) {
                UI.showClosingMessage(
                    data.closing_message || "Cảm ơn bạn đã tham gia buổi phỏng vấn!",
                    () => {
                        UI.showCompletedSummary(data.summary);
                    }
                );
            } else {
                // Nếu BE chưa finish tự động, force close
                alert('✅ Đã lưu kết quả phỏng vấn!');
                this.close();
            }

        } catch (error) {
            console.error('Error ending interview early:', error);
            alert('Lỗi: ' + error.message);
        } finally {
            UI.showLoading(false);
        }
    },

    close() {
        UI.showModal(false);
        Audio.stop();
        Audio.hideControls();
        Timer.hide();
        Voice.stop();

        // ✅ THAY ĐỔI: Không reload, chỉ vẽ lại UI từ local state đã cập nhật
        if (STATE.sessionData && STATE.sessionData.candidates) {
            UI.displayCandidates(STATE.sessionData.candidates);
        }

        // ✅ Cập nhật lại các thẻ thống kê (Hoàn thành, Tiến độ)
        if (STATE.sessionData) {
            try {
                const completedCount = STATE.sessionData.candidates.filter(c => c.status === 'completed').length;
                const totalCount = STATE.sessionData.candidates.length; // Hoặc STATE.sessionData.total_count

                document.getElementById('completedCandidates').textContent = completedCount;

                const progressPercent = (totalCount > 0) ? (completedCount / totalCount) * 100 : 0;
                document.getElementById('progressPercent').textContent = Math.round(progressPercent) + '%';
            } catch (e) {
                console.error("Lỗi cập nhật thống kê:", e);
            }
        }
    },

    finish() {
        this.close();
    }
};

// ==================== UTILITY FUNCTIONS ====================
function toggleCollapse(id) {
    const content = document.getElementById(id);
    const header = content.previousElementSibling;

    content.classList.toggle('active');
    header.classList.toggle('active');
}

// ==================== MAIN FUNCTIONS ====================
async function loadSessionDetail() {
    try {
        UI.showLoading(true, 'Đang tải thông tin...');
        const data = await API.fetchSession(STATE.sessionId);

        if (data.success) {
            STATE.sessionData = data.session;
            UI.displaySessionInfo(STATE.sessionData);
            UI.displayCandidates(STATE.sessionData.candidates);
        } else {
            alert('Lỗi: ' + data.error);
        }
    } catch (error) {
        console.error('Error loading session:', error);
        alert('Lỗi tải dữ liệu!');
    } finally {
        UI.showLoading(false);
    }
}

async function exportResults() {
    window.location.href = `${STATE.basePath}/interview_batch/export/${STATE.sessionId}`;
}

async function deleteSession() {
    if (!confirm('Bạn có chắc muốn xóa buổi phỏng vấn này?')) return;

    try {
        const data = await API.deleteSession(STATE.sessionId);
        if (data.success) {
            alert('Đã xóa buổi phỏng vấn!');
            window.location.href = `${STATE.basePath}/interview_batch`;
        }
    } catch (error) {
        alert('Lỗi xóa buổi phỏng vấn!');
    }
}

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', function() {
    // Get session ID
    const sessionIdElement = document.getElementById('sessionIdData');
    STATE.sessionId = sessionIdElement ? sessionIdElement.value : window.SESSION_ID;

    // Initialize voice recognition
    Voice.init();

    loadSessionDetail();

    // Auto-expand textarea
    const textarea = document.getElementById('answerTextarea');
    if (textarea) {
        textarea.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
        });
    }

    // ✅ Cleanup khi đóng tab/window
    window.addEventListener('beforeunload', () => {
        Timer.stop();
        Voice.stop();
        Audio.stop();
    });
});


