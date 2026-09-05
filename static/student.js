document.addEventListener('DOMContentLoaded', () => {
  const socket = io({
    transports: ['polling', 'websocket'],
    reconnection: true,
    reconnectionAttempts: Infinity,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    timeout: 20000
  });
  const connStatus = document.getElementById('connStatus');

  let selectedCourse = '원가회계';
  let selectedSession = '1주차';
  let sessionMap = {};

  const COURSE_PROMPTS = {
    '원가회계': [
      { label: '# CVP 손익분기점', prompt: 'CVP 손익분기점(BEP) 공식과 단위당 공헌이익 개념을 쉽게 설명해줘.' },
      { label: '# 활동기준원가(ABC)', prompt: '활동기준원가계산(ABC)의 도입 배경과 원가동인 배부 절차를 알려줘.' },
      { label: '# 변동원가 vs 고정원가', prompt: '변동원가와 고정원가의 조업도 변동에 따른 총액 및 단위당 원가 특성을 비교해줘.' },
      { label: '# 안전한계율', prompt: '안전한계율(Margin of Safety)의 정의와 공식, 의미를 알려줘.' }
    ],
    '회계감사': [
      { label: '# 감사의견 4가지', prompt: '회계감사 감사의견 4가지(적정, 한정, 부적정, 의견거절)의 결정 기준 차이를 설명해줘.' },
      { label: '# 감사위험 모델', prompt: '감사위험 모델(고유위험 × 통제위험 × 적발위험)의 개념과 감사인의 통제 방법을 알려줘.' },
      { label: '# 내부회계관리제도', prompt: '내부회계관리제도(ICFR)의 평가 및 감사인의 인증 기준은 무엇인가요?' },
      { label: '# 핵심감사사항(KAM)', prompt: '감사보고서 내 핵심감사사항(KAM)의 도입 취지와 기재 예시를 알려줘.' }
    ],
    '캡스톤디자인(ESG공시)': [
      { label: '# ESG Scope 1·2·3', prompt: 'ESG 온실가스 배출량 공시에서 Scope 1, 2, 3의 차이점과 실무 예시를 설명해줘.' },
      { label: '# ISSB IFRS S1·S2', prompt: 'ISSB(국제지속가능성기준위원회) IFRS S1과 S2의 핵심 공시 원칙을 요약해줘.' },
      { label: '# 이중 중요성', prompt: 'ESG 공시에서 재무적 중요성과 환경사회적 영향 중요성(이중 중요성)의 개념은?' },
      { label: '# 지속가능보고서 실습', prompt: '캡스톤 프로젝트 지속가능경영보고서 작성 시 기후 위험 거버넌스 기재 방법은?' }
    ]
  };

  socket.on('connect', () => {
    connStatus.className = 'status-badge online';
    connStatus.innerText = '수업 연결됨';
    if (typeof syncActiveQuizAndCourse === 'function') syncActiveQuizAndCourse();
  });

  if (socket.io) {
    socket.io.on('reconnect', () => {
      console.log('[Student] Socket reconnected - syncing state...');
      if (typeof syncActiveQuizAndCourse === 'function') syncActiveQuizAndCourse();
    });
  }

  socket.on('disconnect', () => {
    connStatus.className = 'status-badge';
    connStatus.style.backgroundColor = '#fee2e2';
    connStatus.style.color = '#991b1b';
    connStatus.innerText = '연결 끊김';
  });

  // 1. 초기 과목 및 세션 로드
  const courseTabs = document.getElementById('studentCourseTabs');
  const sessionSelect = document.getElementById('studentSessionSelect');
  const studentCardCourse = document.getElementById('studentCardCourse');
  const studentCardSession = document.getElementById('studentCardSession');
  const chatCourseTitle = document.getElementById('chatCourseTitle');
  const tagsContainer = document.getElementById('chatTagsContainer');

  let userManuallySelected = false;

  function renderCourseTabs(courses, activeCourse) {
    if (!courses || courses.length === 0) courses = ['원가회계'];
    courseTabs.innerHTML = '';
    courses.forEach(c => {
      const btn = document.createElement('button');
      btn.className = `course-tab-btn ${c === activeCourse ? 'active' : ''}`;
      btn.setAttribute('data-course', c);
      btn.innerText = c;
      courseTabs.appendChild(btn);
    });
  }

  async function loadCourses() {
    try {
      const res = await fetch('/api/courses');
      const data = await res.json();

      // 학생이 이전에 직접 선택한 과목이 있다면 우선 유지
      const savedCourse = localStorage.getItem('student_selected_course');
      if (savedCourse && data.courses && data.courses.includes(savedCourse)) {
        selectedCourse = savedCourse;
        userManuallySelected = true;
      } else {
        selectedCourse = data.active_course || (data.courses && data.courses[0]) || '원가회계';
      }

      selectedSession = data.active_session || '1주차';
      sessionMap = data.session_map || {};

      activeQuizzes = data.active_quizzes || (data.active_quiz ? [data.active_quiz] : []);

      renderCourseTabs(data.courses || ['원가회계'], selectedCourse);
      applyCourseUI();
    } catch (err) {
      console.error('[Student] 과목 로드 오류:', err);
    }
  }

  function applyCourseUI() {
    // 탭 활성화 상태
    document.querySelectorAll('#studentCourseTabs .course-tab-btn').forEach(btn => {
      if (btn.getAttribute('data-course') === selectedCourse) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // 세션 드롭다운 갱신
    const sessions = sessionMap[selectedCourse] || ['1주차', '2주차', '3주차'];
    sessionSelect.innerHTML = '';
    sessions.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.innerText = s;
      if (s === selectedSession) opt.selected = true;
      sessionSelect.appendChild(opt);
    });

    if (studentCardCourse) studentCardCourse.innerText = selectedCourse;
    if (studentCardSession) studentCardSession.innerText = selectedSession;
    if (chatCourseTitle) chatCourseTitle.innerText = selectedCourse;

    const studentHeaderSubtitle = document.getElementById('studentHeaderSubtitle');
    if (studentHeaderSubtitle) {
      studentHeaderSubtitle.innerText = `현재 수강: ${selectedCourse} (${selectedSession})`;
    }

    const welcomeBubble = document.getElementById('welcomeBotBubble');
    if (welcomeBubble) {
      welcomeBubble.innerHTML = `
        <div class="bot-header">🎓 [${escapeHtml(selectedCourse)}] AI 전담 조교</div>
        안녕하세요! <b>${escapeHtml(selectedCourse)}</b> 전문 대학 수업 조교입니다. 😊<br>
        수업 중 이해가 잘 안 되거나 개념/공식 질문이 있다면 언제든 편하게 물어보세요!
      `;
    }

    // AI 조교 태그 갱신
    renderChatTags();

    // 현재 선택된 과목 및 차시와 일치하는 퀴즈만 노출
    if (typeof updateQuizDisplay === 'function') {
      updateQuizDisplay();
    }
  }

  function renderChatTags() {
    tagsContainer.innerHTML = '';
    let prompts = COURSE_PROMPTS[selectedCourse];
    if (!prompts || prompts.length === 0) {
      prompts = [
        { label: `# ${selectedCourse} 핵심 개념`, prompt: `${selectedCourse} 수업의 핵심 개념과 기초 이론을 쉽게 설명해줘.` },
        { label: '# 공식 및 핵심 원리', prompt: `${selectedCourse}에서 반드시 알아야 할 주요 공식과 적용 원리를 알려줘.` },
        { label: '# 실무 적용 사례', prompt: `${selectedCourse}와 관련된 실무 및 기업 현장 적용 사례를 소개해줘.` },
        { label: '# 시험 대비 요약', prompt: `${selectedCourse} 시험이나 퀴즈에 자주 출제되는 핵심 포인트를 정리해줘.` }
      ];
    }
    prompts.forEach(p => {
      const btn = document.createElement('button');
      btn.className = 'tag-btn';
      btn.innerText = p.label;
      btn.addEventListener('click', () => sendChatMessage(p.prompt));
      tagsContainer.appendChild(btn);
    });
  }

  // 학생 과목 직접 변경
  courseTabs.addEventListener('click', (e) => {
    if (!e.target.classList.contains('course-tab-btn')) return;
    selectedCourse = e.target.getAttribute('data-course');
    userManuallySelected = true;
    try {
      localStorage.setItem('student_selected_course', selectedCourse);
    } catch (e) {}

    const available = sessionMap[selectedCourse] || ['1주차'];
    selectedSession = available[0] || '1주차';
    applyCourseUI();
  });

  sessionSelect.addEventListener('change', () => {
    selectedSession = sessionSelect.value;
    if (studentCardSession) studentCardSession.innerText = selectedSession;
    const studentHeaderSubtitle = document.getElementById('studentHeaderSubtitle');
    if (studentHeaderSubtitle) {
      studentHeaderSubtitle.innerText = `현재 수강: ${selectedCourse} (${selectedSession})`;
    }
    if (typeof updateQuizDisplay === 'function') {
      updateQuizDisplay();
    }
  });

  // 교수가 활성 세션을 변경했을 때 수신
  socket.on('session_changed', (data) => {
    console.log('[Student] session_changed received:', data);
    if (data && data.active_course) {
      // 학생이 직접 다른 과목을 선택하지 않았거나, 현재 선택 과목이 목록에 없을 때만 자동 동기화
      if (!userManuallySelected) {
        selectedCourse = data.active_course;
        if (data.active_session) selectedSession = data.active_session;
        applyCourseUI();
      }
    }
  });

  // 교수가 과목을 추가/수정/삭제했을 때 실시간 갱신
  socket.on('courses_updated', (data) => {
    console.log('[Student] courses_updated received:', data);
    if (!data || !data.courses) return;
    sessionMap = data.session_map || sessionMap;

    if (data.renamed && data.renamed.old_name === selectedCourse) {
      selectedCourse = data.renamed.new_name;
      try {
        localStorage.setItem('student_selected_course', selectedCourse);
      } catch (e) {}
    } else if (!data.courses.includes(selectedCourse)) {
      selectedCourse = data.active_course || data.courses[0];
      userManuallySelected = false;
      try {
        localStorage.removeItem('student_selected_course');
      } catch (e) {}
      const available = sessionMap[selectedCourse] || ['1주차'];
      selectedSession = available[0] || '1주차';
    }

    renderCourseTabs(data.courses, selectedCourse);
    applyCourseUI();
  });

  // 2. 실시간 피드백 제출
  let selectedCategory = '이해 완료';
  const reactionBtns = document.querySelectorAll('.reaction-btn');
  const opinionText = document.getElementById('opinionText');
  const submitOpinionBtn = document.getElementById('submitOpinionBtn');
  const submitNotice = document.getElementById('submitNotice');

  reactionBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      reactionBtns.forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedCategory = btn.getAttribute('data-cat');
    });
  });

  submitOpinionBtn.addEventListener('click', () => {
    const text = opinionText.value.trim();
    socket.emit('submit_opinion', {
      course: selectedCourse,
      session: selectedSession,
      category: selectedCategory,
      text: text
    });

    submitNotice.style.display = 'block';
    opinionText.value = '';
    setTimeout(() => {
      submitNotice.style.display = 'none';
    }, 3000);
  });

  // 3. 실시간 퀴즈 수신 및 답안 제출 (동일 차시 다중 문제 지원 & 완벽 격리)
  let activeQuizzes = [];
  // 학생 답안 상태: key = quiz_id (또는 `${course}_${session}_${question}`) -> { selectedIndex, isCorrect }
  const answeredQuizzesStore = {};

  function getQuizId(quiz) {
    if (!quiz) return '';
    return quiz.id || `${quiz.course || ''}__${quiz.session || ''}__${quiz.question || ''}`;
  }

  // 현재 학생이 선택하여 보고 있는 [과목]과 [차시]에 일치하는 퀴즈 목록 필터링
  function getMatchingQuizzesForCurrentView() {
    return activeQuizzes.filter(q => {
      if (!q || !q.question) return false;
      const qCourse = (q.course || '').trim();
      const qSession = (q.session || '').trim();
      const currCourse = (selectedCourse || '').trim();
      const currSession = (selectedSession || '').trim();
      const courseMatches = (!qCourse || qCourse === currCourse);
      const sessionMatches = (!qSession || qSession === currSession);
      return courseMatches && sessionMatches;
    });
  }

  // 퀴즈 화면 렌더링 (다중 문제 카드 지원)
  function updateQuizDisplay(shouldScroll = false) {
    const qc = document.getElementById('quiz-container') || document.getElementById('quizContainer');
    if (!qc) return;

    const matchingQuizzes = getMatchingQuizzesForCurrentView();

    if (matchingQuizzes.length === 0) {
      qc.style.display = 'none';
      qc.classList.remove('active');
      qc.innerHTML = '';
      return;
    }

    qc.style.display = 'block';
    qc.classList.add('active');

    let html = `
      <div class="quiz-badge" style="background:#16a34a; color:white; font-size:0.8rem; font-weight:700; padding:4px 10px; border-radius:4px; display:inline-block; margin-bottom:0.75rem;">
        ⚡ [${escapeHtml(selectedCourse)} - ${escapeHtml(selectedSession)}] 실시간 퀴즈 (총 ${matchingQuizzes.length}문제)
      </div>
      <div style="display: flex; flex-direction: column; gap: 1.25rem;">
    `;

    matchingQuizzes.forEach((quiz, idx) => {
      const qId = getQuizId(quiz);
      const savedAnswer = answeredQuizzesStore[qId];
      const isAnswered = !!savedAnswer;
      const optList = Array.isArray(quiz.options) ? quiz.options : [];

      let optionsHtml = '';
      optList.forEach((opt, optIdx) => {
        let extraClass = '';
        let badgeText = '';

        if (isAnswered) {
          if (optIdx === parseInt(quiz.answer)) {
            extraClass = ' correct';
            badgeText = ' <b>(정답 ✓)</b>';
          } else if (optIdx === savedAnswer.selectedIndex) {
            extraClass = ' wrong';
            badgeText = ' <b>(내 제출 ✗)</b>';
          }
        }

        optionsHtml += `
          <button type="button" class="quiz-opt-btn${extraClass}" data-quiz-id="${escapeHtml(qId)}" data-idx="${optIdx}" ${isAnswered ? 'disabled style="cursor:default;"' : ''}>
            ${optIdx + 1}. ${escapeHtml(opt)}${badgeText}
          </button>
        `;
      });

      let resultHtml = '';
      if (isAnswered) {
        if (savedAnswer.isCorrect) {
          resultHtml = `
            <div style="margin-top: 0.6rem; padding: 0.6rem; border-radius: 6px; font-size: 0.85rem; background-color: #dcfce7; color: #15803d;">
              <b>🎉 정답입니다!</b><br>${escapeHtml(quiz.explanation || '')}
            </div>
          `;
        } else {
          resultHtml = `
            <div style="margin-top: 0.6rem; padding: 0.6rem; border-radius: 6px; font-size: 0.85rem; background-color: #fee2e2; color: #b91c1c;">
              <b>오답입니다.</b> (정답: ${parseInt(quiz.answer) + 1}번)<br>${escapeHtml(quiz.explanation || '')}
            </div>
          `;
        }
      }

      html += `
        <div class="quiz-question-card" data-quiz-id="${escapeHtml(qId)}" style="background: #ffffff; border: 1px solid var(--border); border-radius: 8px; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
            <span style="font-size: 0.85rem; font-weight: 700; color: #4f46e5; background: #eef2ff; padding: 2px 8px; border-radius: 4px;">
              문제 ${idx + 1}
            </span>
            ${isAnswered ? `<span style="font-size: 0.78rem; font-weight: 600; color: ${savedAnswer.isCorrect ? '#16a34a' : '#dc2626'};">제출 완료</span>` : '<span style="font-size: 0.78rem; color: #f59e0b; font-weight: 600;">답변 대기 중</span>'}
          </div>
          <h4 style="font-size: 1.05rem; font-weight: 700; color: #0f172a; margin-bottom: 0.6rem; line-height: 1.35;">
            ${escapeHtml(quiz.question)}
          </h4>
          <div class="quiz-options" style="display: flex; flex-direction: column; gap: 0.4rem; margin: 0.5rem 0;">
            ${optionsHtml}
          </div>
          ${resultHtml}
        </div>
      `;
    });

    html += `</div>`;
    qc.innerHTML = html;

    // 옵션 클릭 리스너 등록
    qc.querySelectorAll('.quiz-opt-btn:not([disabled])').forEach(btn => {
      btn.addEventListener('click', () => {
        const qId = btn.getAttribute('data-quiz-id');
        const optIdx = parseInt(btn.getAttribute('data-idx'), 10);
        submitQuizAnswer(qId, optIdx);
      });
    });

    if (shouldScroll) {
      qc.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  function submitQuizAnswer(quizId, selectedIndex) {
    const quiz = activeQuizzes.find(q => getQuizId(q) === quizId);
    if (!quiz) return;

    if (answeredQuizzesStore[quizId]) return;

    const isCorrect = (selectedIndex === parseInt(quiz.answer));
    answeredQuizzesStore[quizId] = {
      selectedIndex: selectedIndex,
      isCorrect: isCorrect
    };

    socket.emit('submit_quiz_answer', {
      quiz_id: quiz.id,
      selected_option: selectedIndex,
      course: quiz.course,
      session: quiz.session
    });

    updateQuizDisplay(false);
  }

  // 소켓 이벤트: 활성 퀴즈 전체 갱신
  socket.on('active_quizzes_updated', (data) => {
    console.log('[Student] active_quizzes_updated:', data);
    if (!data) return;
    activeQuizzes = data.active_quizzes || [];
    updateQuizDisplay(false);
  });

  // 소켓 이벤트: 신규 퀴즈 수신
  socket.on('quiz_added', (quiz) => {
    console.log('[Student] quiz_added:', quiz);
    if (!quiz) return;
    const exists = activeQuizzes.find(q => getQuizId(q) === getQuizId(quiz));
    if (!exists) activeQuizzes.push(quiz);
    const matches = getMatchingQuizzesForCurrentView().some(q => getQuizId(q) === getQuizId(quiz));
    updateQuizDisplay(matches);
  });

  // 소켓 이벤트: 퀴즈 삭제 수신
  socket.on('quiz_deleted', (data) => {
    console.log('[Student] quiz_deleted:', data);
    if (!data || !data.quiz_id) return;
    activeQuizzes = activeQuizzes.filter(q => q.id !== data.quiz_id);
    updateQuizDisplay(false);
  });

  // 레거시 이벤트 호환 (send_quiz & receive_quiz)
  socket.on('send_quiz', (quiz) => {
    console.log('[Student] send_quiz received:', quiz);
    if (!quiz) return;
    const exists = activeQuizzes.find(q => getQuizId(q) === getQuizId(quiz));
    if (!exists) activeQuizzes.push(quiz);
    const matches = getMatchingQuizzesForCurrentView().length > 0;
    updateQuizDisplay(matches);
  });

  socket.on('receive_quiz', (quiz) => {
    console.log('[Student] receive_quiz received:', quiz);
    if (!quiz) return;
    const exists = activeQuizzes.find(q => getQuizId(q) === getQuizId(quiz));
    if (!exists) activeQuizzes.push(quiz);
    const matches = getMatchingQuizzesForCurrentView().length > 0;
    updateQuizDisplay(matches);
  });

  // 교수 화면의 문제 출제 취소(clear_quiz) 수신
  socket.on('clear_quiz', (data) => {
    console.log('[Student] clear_quiz event received:', data);
    if (data && data.course && data.session) {
      activeQuizzes = activeQuizzes.filter(q => !(q.course === data.course && q.session === data.session));
    } else {
      activeQuizzes = [];
    }
    updateQuizDisplay(false);
  });

  // 모바일 절전 복귀 및 소켓 유실 완벽 방어: 활성 퀴즈 상태 동기화
  let isSyncingQuiz = false;
  async function syncActiveQuizAndCourse() {
    if (isSyncingQuiz) return;
    isSyncingQuiz = true;
    try {
      const res = await fetch('/api/current_quiz?_t=' + Date.now());
      if (!res.ok) return;
      const data = await res.json();
      activeQuizzes = data.active_quizzes || (data.active_quiz ? [data.active_quiz] : []);
      updateQuizDisplay(false);
    } catch (err) {
      // 백그라운드 동기화 오류는 조용히 무시
    } finally {
      isSyncingQuiz = false;
    }
  }

  // 모바일 화면 켜짐 / 탭 복귀 감지 (Page Visibility API)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      console.log('[Student] Screen visible (wake up) - checking active quiz...');
      syncActiveQuizAndCourse();
    }
  });

  window.addEventListener('focus', () => syncActiveQuizAndCourse());
  window.addEventListener('pageshow', () => syncActiveQuizAndCourse());

  // 3초 주기 초경량 자동 백그라운드 동기화 (모바일 소켓 유실 방어)
  setInterval(syncActiveQuizAndCourse, 3000);

  // 4. AI 챗봇 대화 처리
  const chatHistory = document.getElementById('chatHistory');
  const chatInput = document.getElementById('chatInput');
  const sendChatBtn = document.getElementById('sendChatBtn');

  function appendMessage(sender, text, isBot = false) {
    const bubble = document.createElement('div');
    bubble.className = `message-bubble ${isBot ? 'bot' : 'user'}`;

    if (isBot) {
      const header = document.createElement('div');
      header.className = 'bot-header';
      header.innerHTML = `🎓 [${selectedCourse}] AI 전담 조교`;
      bubble.appendChild(header);

      const content = document.createElement('div');
      content.innerText = text;
      bubble.appendChild(content);
    } else {
      bubble.innerText = text;
    }

    chatHistory.appendChild(bubble);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return bubble;
  }

  let currentLoadingBubble = null;

  function sendChatMessage(message) {
    const text = (message || chatInput.value).trim();
    if (!text) return;

    appendMessage('user', text, false);
    chatInput.value = '';

    currentLoadingBubble = appendMessage('bot', '답변을 작성하고 있습니다... ⏳', true);

    socket.emit('chat_message', {
      message: text,
      course: selectedCourse
    });
  }

  socket.on('chat_response', (data) => {
    if (currentLoadingBubble && currentLoadingBubble.parentNode) {
      currentLoadingBubble.remove();
      currentLoadingBubble = null;
    }
    const reply = data.response || '답변을 불러오지 못했습니다.';
    appendMessage('bot', reply, true);
  });

  sendChatBtn.addEventListener('click', () => sendChatMessage());
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendChatMessage();
  });

  function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  loadCourses();
});
