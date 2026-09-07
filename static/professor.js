document.addEventListener('DOMContentLoaded', () => {
  const socket = io();
  const profConnStatus = document.getElementById('profConnStatus');

  let currentCourse = '원가회계';
  let currentSession = '1주차';
  let sessionMap = {};

  socket.on('connect', () => {
    profConnStatus.className = 'status-badge online';
    profConnStatus.innerText = '실시간 연결됨';
  });

  socket.on('disconnect', () => {
    profConnStatus.className = 'status-badge';
    profConnStatus.style.backgroundColor = '#fee2e2';
    profConnStatus.style.color = '#991b1b';
    profConnStatus.innerText = '연결 끊김';
  });

  // 1. Chart.js 인스턴스 초기화
  // 1-1. 실시간 차트
  const ctxOpinions = document.getElementById('opinionsChart').getContext('2d');
  const opinionsChart = new Chart(ctxOpinions, {
    type: 'bar',
    data: {
      labels: ['이해 완료', '조금 어려움', '질문 있음', '예제 필요'],
      datasets: [{
        label: '학생 응답 수',
        data: [0, 0, 0, 0],
        backgroundColor: [
          'rgba(16, 185, 129, 0.85)',
          'rgba(245, 158, 11, 0.85)',
          'rgba(239, 68, 68, 0.85)',
          'rgba(6, 182, 212, 0.85)'
        ],
        borderColor: ['#10b981', '#f59e0b', '#ef4444', '#06b6d4'],
        borderWidth: 1.5,
        borderRadius: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1 } }
      },
      plugins: { legend: { display: false } }
    }
  });

  // 1-2. 퀴즈 실시간 응답 차트
  const ctxQuiz = document.getElementById('quizStatsChart').getContext('2d');
  const quizChart = new Chart(ctxQuiz, {
    type: 'bar',
    data: {
      labels: ['보기 1', '보기 2', '보기 3', '보기 4'],
      datasets: [{
        label: '응답자 수',
        data: [0, 0, 0, 0],
        backgroundColor: 'rgba(99, 102, 241, 0.8)',
        borderColor: '#6366f1',
        borderWidth: 1,
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { beginAtZero: true, ticks: { stepSize: 1 } }
      },
      plugins: { legend: { display: false } }
    }
  });

  // 1-3. 누적 주차별 이해도 추이 차트
  const ctxTrend = document.getElementById('cumulativeTrendChart').getContext('2d');
  const cumulativeTrendChart = new Chart(ctxTrend, {
    type: 'bar',
    data: {
      labels: [],
      datasets: [
        { label: '이해 완료', data: [], backgroundColor: 'rgba(16, 185, 129, 0.8)' },
        { label: '조금 어려움', data: [], backgroundColor: 'rgba(245, 158, 11, 0.8)' },
        { label: '질문 있음', data: [], backgroundColor: 'rgba(239, 68, 68, 0.8)' },
        { label: '예제 필요', data: [], backgroundColor: 'rgba(6, 182, 212, 0.8)' }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { stacked: true },
        y: { stacked: true, beginAtZero: true, ticks: { stepSize: 1 } }
      },
      plugins: {
        legend: { position: 'top' }
      }
    }
  });

  // 2. 초기 과목 및 세션 데이터 로드
  const courseTabs = document.getElementById('courseTabs');
  const sessionSelect = document.getElementById('sessionSelect');
  const currentCourseDisplay = document.getElementById('currentCourseDisplay');
  const currentSessionDisplay = document.getElementById('currentSessionDisplay');
  const analysisTargetSession = document.getElementById('analysisTargetSession');

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

    const profHeaderSubtitle = document.getElementById('profHeaderSubtitle');
    if (profHeaderSubtitle) {
      profHeaderSubtitle.innerText = courses.join(' · ');
    }

    const deleteBtn = document.getElementById('deleteCourseBtn');
    if (deleteBtn) {
      deleteBtn.style.display = courses.length > 1 ? 'inline-flex' : 'none';
    }
  }

  async function loadInitialCourses() {
    try {
      const res = await fetch('/api/courses');
      const data = await res.json();
      currentCourse = data.active_course || '원가회계';
      currentSession = data.active_session || '1주차';
      sessionMap = data.session_map || {};
      activeQuizzes = data.active_quizzes || [];
      quizStats = data.quiz_stats || {};

      renderCourseTabs(data.courses || ['원가회계'], currentCourse);
      updateSessionDropdown();
      fetchGraphData();
      if (typeof renderProfessorQuizDashboard === 'function') {
        renderProfessorQuizDashboard();
      }
    } catch (err) {
      console.error('과목 정보 로드 오류:', err);
    }
  }

  function updateSessionDropdown() {
    const sessions = sessionMap[currentCourse] || ['1주차', '2주차', '3주차'];
    sessionSelect.innerHTML = '';

    sessions.forEach(s => {
      const opt = document.createElement('option');
      opt.value = s;
      opt.innerText = s;
      if (s === currentSession) opt.selected = true;
      sessionSelect.appendChild(opt);
    });

    const allOpt = document.createElement('option');
    allOpt.value = '전체';
    allOpt.innerText = '전체 (누적 합산)';
    if (currentSession === '전체') allOpt.selected = true;
    sessionSelect.appendChild(allOpt);

    currentCourseDisplay.innerText = currentCourse;
    currentSessionDisplay.innerText = currentSession;
    analysisTargetSession.innerText = currentSession;

    if (typeof renderProfessorQuizDashboard === 'function') {
      renderProfessorQuizDashboard();
    }
  }

  // 3. 과목 탭 전환 이벤트
  courseTabs.addEventListener('click', async (e) => {
    if (!e.target.classList.contains('course-tab-btn')) return;
    document.querySelectorAll('.course-tab-btn').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');

    currentCourse = e.target.getAttribute('data-course');
    const available = sessionMap[currentCourse] || ['1주차'];
    currentSession = available[0] || '1주차';

    updateSessionDropdown();
    fetchGraphData();
    updateCumulativeStats();

    // 교수 화면에서 과목 변경 시 서버 활성 과목 및 학생 화면에 자동 동기화
    try {
      await fetch('/api/set_active_session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course: currentCourse, session: currentSession })
      });
      console.log(`[Professor] Active course synced to [${currentCourse} - ${currentSession}]`);
    } catch (err) {
      console.warn('활성 수업 자동 동기화 오류:', err);
    }
  });

  // 세션 드롭다운 변경 이벤트
  sessionSelect.addEventListener('change', async () => {
    currentSession = sessionSelect.value;
    currentSessionDisplay.innerText = currentSession;
    analysisTargetSession.innerText = currentSession;
    fetchGraphData();

    if (currentSession !== '전체') {
      try {
        await fetch('/api/set_active_session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ course: currentCourse, session: currentSession })
        });
      } catch (err) {
        console.warn('세션 변경 동기화 오류:', err);
      }
    }
  });

  // 새 차시 추가 버튼
  const addSessionBtn = document.getElementById('addSessionBtn');
  addSessionBtn.addEventListener('click', async () => {
    const newName = prompt(`[${currentCourse}] 추가할 새로운 강의시간(차시/주차명)을 입력하세요:`, '4주차');
    if (!newName || !newName.trim()) return;

    try {
      const res = await fetch('/api/add_session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course: currentCourse, session_name: newName.trim() })
      });
      const data = await res.json();
      if (data.success) {
        sessionMap[currentCourse] = data.sessions;
        currentSession = data.active_session;
        updateSessionDropdown();
        fetchGraphData();
        alert(`'${newName.trim()}' 차시가 성공적으로 등록되었습니다.`);
      }
    } catch (err) {
      alert('차시 추가 중 오류가 발생했습니다.');
    }
  });

  // 현재 강의로 지정 버튼
  const setActiveSessionBtn = document.getElementById('setActiveSessionBtn');
  setActiveSessionBtn.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/set_active_session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course: currentCourse, session: currentSession })
      });
      const data = await res.json();
      if (data.success) {
        alert(`현재 진행 수업이 [${currentCourse} - ${currentSession}]으로 설정되었습니다. 학생 화면에 알림이 전송됩니다.`);
      }
    } catch (err) {
      alert('활성 수업 설정 오류');
    }
  });

  // 과목명 수정 버튼
  const renameCourseBtn = document.getElementById('renameCourseBtn');
  if (renameCourseBtn) {
    renameCourseBtn.addEventListener('click', async () => {
      const newName = prompt(`[${currentCourse}] 과목의 새로운 이름을 입력하세요:`, currentCourse);
      if (!newName || !newName.trim() || newName.trim() === currentCourse) return;

      try {
        const res = await fetch('/api/rename_course', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ old_name: currentCourse, new_name: newName.trim() })
        });
        const data = await res.json();
        if (data.success) {
          currentCourse = data.new_name;
          sessionMap = data.session_map || sessionMap;
          renderCourseTabs(data.courses, currentCourse);
          updateSessionDropdown();
          fetchGraphData();
          updateCumulativeStats();
          alert(`과목명이 '${data.new_name}'(으)로 성공적으로 수정되었습니다.`);
        } else {
          alert(data.message || '과목명 수정에 실패했습니다.');
        }
      } catch (err) {
        alert('과목명 수정 중 오류가 발생했습니다.');
      }
    });
  }

  // 새 과목 추가 버튼
  const addCourseBtn = document.getElementById('addCourseBtn');
  if (addCourseBtn) {
    addCourseBtn.addEventListener('click', async () => {
      const newCourseName = prompt('추가할 새로운 과목명을 입력하세요:', '');
      if (!newCourseName || !newCourseName.trim()) return;

      try {
        const res = await fetch('/api/add_course', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ course_name: newCourseName.trim() })
        });
        const data = await res.json();
        if (data.success) {
          currentCourse = data.course_name;
          sessionMap = data.session_map || sessionMap;
          currentSession = '1주차';
          renderCourseTabs(data.courses, currentCourse);
          updateSessionDropdown();
          fetchGraphData();
          updateCumulativeStats();
          alert(`새 과목 '${data.course_name}'이(가) 등록되었습니다.`);

          // 신규 과목을 현재 수업으로 동기화
          fetch('/api/set_active_session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ course: currentCourse, session: currentSession })
          }).catch(() => {});
        } else {
          alert(data.message || '과목 추가에 실패했습니다.');
        }
      } catch (err) {
        alert('과목 추가 중 오류가 발생했습니다.');
      }
    });
  }

  // 과목 삭제 버튼
  const deleteCourseBtn = document.getElementById('deleteCourseBtn');
  if (deleteCourseBtn) {
    deleteCourseBtn.addEventListener('click', async () => {
      if (!confirm(`정말로 '[${currentCourse}]' 과목을 삭제하시겠습니까? 관련된 학생 피드백 데이터가 모두 삭제됩니다.`)) return;

      try {
        const res = await fetch('/api/delete_course', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ course: currentCourse })
        });
        const data = await res.json();
        if (data.success) {
          currentCourse = data.active_course || data.courses[0];
          sessionMap = data.session_map || sessionMap;
          const available = sessionMap[currentCourse] || ['1주차'];
          currentSession = available[0] || '1주차';
          renderCourseTabs(data.courses, currentCourse);
          updateSessionDropdown();
          fetchGraphData();
          updateCumulativeStats();
          alert('과목이 삭제되었습니다.');
        } else {
          alert(data.message || '과목 삭제에 실패했습니다.');
        }
      } catch (err) {
        alert('과목 삭제 중 오류가 발생했습니다.');
      }
    });
  }

  // 4. 그래프 데이터 조회 및 렌더링
  async function fetchGraphData() {
    try {
      const res = await fetch(`/api/graph_data?course=${encodeURIComponent(currentCourse)}&session=${encodeURIComponent(currentSession)}`);
      const data = await res.json();
      applyGraphData(data);
    } catch (err) {
      console.error(err);
    }
  }

  function applyGraphData(data) {
    if (!data) return;

    if (data.counts) {
      opinionsChart.data.datasets[0].data = data.counts;
      opinionsChart.update();
    }

    const totalOpinionsCount = document.getElementById('totalOpinionsCount');
    if (totalOpinionsCount) {
      totalOpinionsCount.innerText = data.total || 0;
    }

    // 최근 피드 목록 갱신
    const opinionsList = document.getElementById('opinionsList');
    if (data.recent_opinions && data.recent_opinions.length > 0) {
      opinionsList.innerHTML = '';
      data.recent_opinions.forEach(op => {
        const item = document.createElement('div');
        const catClass = (op.category || '기타').replace(/\s+/g, '_');
        item.className = `opinion-item ${catClass}`;
        item.innerHTML = `
          <div class="opinion-item-header">
            <b>[${op.session || '일반'}] ${op.category}</b>
            <span>${op.timestamp}</span>
          </div>
          <div>${escapeHtml(op.text)}</div>
        `;
        opinionsList.appendChild(item);
      });
    } else {
      opinionsList.innerHTML = `
        <div style="text-align: center; color: var(--text-muted); padding: 2rem;">
          [${data.course} - ${data.session}] 수집된 학생 의견이 없습니다.
        </div>
      `;
    }

    // 누적 통계 뷰 갱신
    if (data.session_trend) {
      renderTrendChart(data.session_trend);
    }
  }

  socket.on('update_graph', (data) => {
    if (data && data.course === currentCourse && (currentSession === '전체' || data.session === currentSession)) {
      applyGraphData(data);
    }
  });

  socket.on('courses_updated', (data) => {
    if (!data || !data.courses) return;
    sessionMap = data.session_map || sessionMap;

    if (data.renamed && data.renamed.old_name === currentCourse) {
      currentCourse = data.renamed.new_name;
    } else if (!data.courses.includes(currentCourse)) {
      currentCourse = data.active_course || data.courses[0];
      const available = sessionMap[currentCourse] || ['1주차'];
      currentSession = available[0] || '1주차';
    }

    renderCourseTabs(data.courses, currentCourse);
    updateSessionDropdown();
    fetchGraphData();
    updateCumulativeStats();
  });

  // 5. 서브 뷰 모드 전환 (실시간 모니터링 vs 누적 분석 & 종합 해석)
  const tabLiveView = document.getElementById('tabLiveView');
  const tabCumulativeView = document.getElementById('tabCumulativeView');
  const liveViewContainer = document.getElementById('liveViewContainer');
  const cumulativeViewContainer = document.getElementById('cumulativeViewContainer');

  tabLiveView.addEventListener('click', () => {
    tabLiveView.classList.add('active');
    tabCumulativeView.classList.remove('active');
    liveViewContainer.style.display = 'block';
    cumulativeViewContainer.classList.remove('active');
  });

  tabCumulativeView.addEventListener('click', () => {
    tabCumulativeView.classList.add('active');
    tabLiveView.classList.remove('active');
    liveViewContainer.style.display = 'none';
    cumulativeViewContainer.classList.add('active');
    updateCumulativeStats();
  });

  // 6. 누적 분석 뷰 통계 및 차트 렌더링
  function renderTrendChart(trendData) {
    const sessions = Object.keys(trendData);
    const completed = [];
    const difficult = [];
    const questions = [];
    const examples = [];

    sessions.forEach(s => {
      const counts = trendData[s].counts || {};
      completed.push(counts['이해 완료'] || 0);
      difficult.push(counts['조금 어려움'] || 0);
      questions.push(counts['질문 있음'] || 0);
      examples.push(counts['예제 필요'] || 0);
    });

    cumulativeTrendChart.data.labels = sessions;
    cumulativeTrendChart.data.datasets[0].data = completed;
    cumulativeTrendChart.data.datasets[1].data = difficult;
    cumulativeTrendChart.data.datasets[2].data = questions;
    cumulativeTrendChart.data.datasets[3].data = examples;
    cumulativeTrendChart.update();
  }

  async function updateCumulativeStats() {
    document.getElementById('statCourseName').innerText = currentCourse;
    try {
      const res = await fetch(`/api/graph_data?course=${encodeURIComponent(currentCourse)}&session=전체`);
      const data = await res.json();

      const total = data.total || 0;
      const sessCount = (data.available_sessions || []).length;
      document.getElementById('statCumulativeTotal').innerText = `${total}건`;
      document.getElementById('statSessionCount').innerText = `${sessCount}개 주차`;

      const compCount = data.counts ? data.counts[0] : 0;
      const rate = total > 0 ? Math.round((compCount / total) * 100) : 0;
      document.getElementById('statComprehensionRate').innerText = total > 0 ? `${rate}%` : '-';

      if (data.session_trend) {
        renderTrendChart(data.session_trend);
      }
    } catch (err) {
      console.error(err);
    }
  }

  // 7. 누적 종합 진단 AI 리포트 실행
  const runCumulativeAnalysisBtn = document.getElementById('runCumulativeAnalysisBtn');
  const cumulativeReportBox = document.getElementById('cumulativeReportBox');
  const cumulativeReportText = document.getElementById('cumulativeReportText');
  const reportTitle = document.getElementById('reportTitle');

  runCumulativeAnalysisBtn.addEventListener('click', async () => {
    runCumulativeAnalysisBtn.disabled = true;
    runCumulativeAnalysisBtn.innerText = 'AI 종합 진단 리포트 생성 중... ⏳';
    cumulativeReportBox.style.display = 'block';
    reportTitle.innerHTML = `<span>📑</span> [${currentCourse}] 학기 누적 데이터 AI 종합 진단서`;
    cumulativeReportText.innerText = `[${currentCourse}]의 전 주차 누적 피드백 데이터를 종합 분석하여 학습 성취도, 취약 단원 및 향후 강의 개선안을 도출하고 있습니다...`;

    try {
      const res = await fetch('/api/analyze_cumulative', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course: currentCourse })
      });
      const data = await res.json();
      cumulativeReportText.innerText = data.analysis_raw || '분석 결과를 불러오지 못했습니다.';
    } catch (err) {
      cumulativeReportText.innerText = '종합 진단 도중 오류가 발생했습니다.';
    } finally {
      runCumulativeAnalysisBtn.disabled = false;
      runCumulativeAnalysisBtn.innerHTML = '<span>✨</span> 과목 누적 데이터 AI 종합 진단 실행';
    }
  });

  // 8. 실시간 세션 분석 및 퀴즈 출제
  const analyzeBtn = document.getElementById('analyzeOpinionsBtn');
  const analysisCard = document.getElementById('analysisResultCard');
  const analysisContent = document.getElementById('analysisContent');
  const applyQuizBtn = document.getElementById('applySuggestedQuizBtn');
  let lastSuggestedQuiz = null;

  analyzeBtn.addEventListener('click', async () => {
    analyzeBtn.disabled = true;
    analyzeBtn.innerText = '세션 분석 진행 중... ⏳';
    analysisCard.classList.add('active');
    analysisContent.innerText = `[${currentCourse} - ${currentSession}] 학생 피드백을 분석 중입니다...`;

    try {
      const res = await fetch('/api/analyze_opinions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course: currentCourse, session: currentSession })
      });
      const data = await res.json();

      if (data.analysis_raw) {
        analysisContent.innerText = data.analysis_raw;
      } else {
        analysisContent.innerText = `${data.summary || '분석 완료'}\n\n제안: ${data.suggestions || '없음'}`;
      }

      if (data.recommended_quiz) {
        lastSuggestedQuiz = data.recommended_quiz;
        applyQuizBtn.style.display = 'inline-flex';
      }
    } catch (err) {
      analysisContent.innerText = '분석 도중 오류 발생';
    } finally {
      analyzeBtn.disabled = false;
      analyzeBtn.innerHTML = '<span>✨</span> 현재 세션 피드백 AI 분석';
    }
  });

  applyQuizBtn.addEventListener('click', () => {
    if (!lastSuggestedQuiz) return;
    document.getElementById('quizQuestionInput').value = lastSuggestedQuiz.question || '';
    if (lastSuggestedQuiz.options && lastSuggestedQuiz.options.length >= 4) {
      document.getElementById('opt0').value = lastSuggestedQuiz.options[0];
      document.getElementById('opt1').value = lastSuggestedQuiz.options[1];
      document.getElementById('opt2').value = lastSuggestedQuiz.options[2];
      document.getElementById('opt3').value = lastSuggestedQuiz.options[3];
    }
    if (lastSuggestedQuiz.answer !== undefined) {
      document.getElementById('quizCorrectAnswer').value = lastSuggestedQuiz.answer;
    }
    if (lastSuggestedQuiz.explanation) {
      document.getElementById('quizExplanation').value = lastSuggestedQuiz.explanation;
    }
    const qIn = document.getElementById('quizQuestionInput');
    if (qIn) qIn.scrollIntoView({ behavior: 'smooth', block: 'center' });
    alert('추천 퀴즈가 상단 퀴즈 출제 폼에 자동 입력되었습니다!');
  });

  // 9. 다중 퀴즈 출제, 임시 저장 및 문제별 실시간 응답 모니터링
  let editingQuizId = null;

  function getCurrentSessionQuizzes() {
    return activeQuizzes.filter(q => {
      const cMatch = (!q.course || q.course === currentCourse);
      const sMatch = (currentSession === '전체' || !q.session || q.session === currentSession);
      return cMatch && sMatch;
    });
  }

  function renderProfessorQuizDashboard() {
    const sessionBadge = document.getElementById('quizSessionBadge');
    if (sessionBadge) {
      sessionBadge.innerText = `${currentCourse} (${currentSession})`;
    }

    const sessionQuizzes = getCurrentSessionQuizzes();
    const tabsBar = document.getElementById('quizTabsBar');
    const selectedInfo = document.getElementById('selectedQuizInfo');
    const chartWrapper = document.getElementById('quizChartWrapper');
    const noQuiz = document.getElementById('noQuizPlaceholder');
    const draftNotice = document.getElementById('draftQuizNotice');
    const publishBtn = document.getElementById('publishQuizBtn');
    const unpublishBtn = document.getElementById('unpublishQuizBtn');

    if (sessionQuizzes.length === 0) {
      if (tabsBar) tabsBar.innerHTML = '';
      if (selectedInfo) selectedInfo.style.display = 'none';
      if (chartWrapper) chartWrapper.style.display = 'none';
      if (draftNotice) draftNotice.style.display = 'none';
      if (noQuiz) noQuiz.style.display = 'block';
      selectedQuizId = null;
      return;
    }

    if (noQuiz) noQuiz.style.display = 'none';
    if (selectedInfo) selectedInfo.style.display = 'block';

    // 선택된 퀴즈 ID가 유효하지 않으면 첫 번째 퀴즈 선택
    if (!selectedQuizId || !sessionQuizzes.find(q => q.id === selectedQuizId)) {
      selectedQuizId = sessionQuizzes[0].id;
    }

    // 탭 바 렌더링 (임시 저장 / 공개 상태 뱃지 표시)
    if (tabsBar) {
      tabsBar.innerHTML = '';
      sessionQuizzes.forEach((q, idx) => {
        const stat = quizStats[q.id];
        const count = (stat && stat.total_responses) || 0;
        const btn = document.createElement('button');
        btn.type = 'button';
        const isSelected = (q.id === selectedQuizId);
        const isPub = (q.is_published === true);
        btn.className = `quiz-tab-btn ${isSelected ? 'active' : ''}`;
        btn.style.cssText = `padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; cursor: pointer; transition: all 0.2s; border: 1px solid ${isSelected ? '#4f46e5' : '#cbd5e1'}; background: ${isSelected ? '#4f46e5' : '#ffffff'}; color: ${isSelected ? '#ffffff' : '#334155'}; white-space: nowrap;`;

        const badgeHtml = isPub
          ? `<span style="background:${isSelected ? 'rgba(255,255,255,0.3)' : '#dcfce7'}; color:${isSelected ? '#ffffff' : '#15803d'}; padding: 1px 5px; border-radius: 4px; font-size: 0.72rem; margin-left: 3px; font-weight: 700;">공개 ${count}명</span>`
          : `<span style="background:${isSelected ? 'rgba(255,255,255,0.3)' : '#fef3c7'}; color:${isSelected ? '#ffffff' : '#b45309'}; padding: 1px 5px; border-radius: 4px; font-size: 0.72rem; margin-left: 3px; font-weight: 700;">🔒임시</span>`;

        btn.innerHTML = `문제 ${idx + 1} ${badgeHtml}`;
        btn.addEventListener('click', () => {
          selectedQuizId = q.id;
          renderProfessorQuizDashboard();
        });
        tabsBar.appendChild(btn);
      });
    }

    // 선택된 퀴즈 상세 갱신
    const currentQuiz = sessionQuizzes.find(q => q.id === selectedQuizId) || sessionQuizzes[0];
    const qIndex = sessionQuizzes.indexOf(currentQuiz) + 1;
    const isCurrentPub = (currentQuiz.is_published === true);

    const statusBadge = document.getElementById('selectedQuizStatusBadge');
    if (statusBadge) {
      if (isCurrentPub) {
        statusBadge.innerText = '🟢 학생에게 공개 중';
        statusBadge.style.background = '#dcfce7';
        statusBadge.style.color = '#15803d';
        statusBadge.style.border = '1px solid #bbf7d0';
      } else {
        statusBadge.innerText = '🔒 임시 저장 (미공개)';
        statusBadge.style.background = '#fef3c7';
        statusBadge.style.color = '#b45309';
        statusBadge.style.border = '1px solid #fde68a';
      }
    }

    if (publishBtn) publishBtn.style.display = isCurrentPub ? 'none' : 'inline-block';
    if (unpublishBtn) unpublishBtn.style.display = isCurrentPub ? 'inline-block' : 'none';

    const titleEl = document.getElementById('selectedQuizTitle');
    if (titleEl) {
      titleEl.innerHTML = `<span style="background: #e0e7ff; color: #3730a3; padding: 2px 6px; border-radius: 4px; font-size: 0.78rem; margin-right: 6px;">문제 ${qIndex}</span> ${escapeHtml(currentQuiz.question)}`;
    }

    const countEl = document.getElementById('quizResponseCount');
    const currentStat = quizStats[currentQuiz.id] || { total_responses: 0, stats: {} };
    if (countEl) {
      countEl.innerText = currentStat.total_responses || 0;
    }

    const answerBadge = document.getElementById('selectedQuizAnswerBadge');
    if (answerBadge) {
      const ansIdx = parseInt(currentQuiz.answer, 10);
      const ansText = currentQuiz.options && currentQuiz.options[ansIdx] ? `: ${escapeHtml(currentQuiz.options[ansIdx])}` : '';
      answerBadge.innerText = `보기 ${ansIdx + 1}${ansText ? ' (' + ansText.substring(0, 15) + '...)' : ''}`;
    }

    // 상태에 따른 차트 또는 임시저장 안내 분기
    if (isCurrentPub) {
      if (draftNotice) draftNotice.style.display = 'none';
      if (chartWrapper) chartWrapper.style.display = 'block';

      if (typeof quizChart !== 'undefined' && quizChart.data) {
        const opts = currentQuiz.options || ['보기 1', '보기 2', '보기 3', '보기 4'];
        quizChart.data.labels = opts.map((opt, i) => {
          const short = opt.length > 12 ? opt.substring(0, 12) + '…' : opt;
          return `보기 ${i + 1}: ${short}`;
        });

        const sMap = currentStat.stats || {};
        const ansIdx = parseInt(currentQuiz.answer, 10);
        const dataVals = opts.map((_, i) => sMap[i] || 0);
        const bgColors = opts.map((_, i) => i === ansIdx ? 'rgba(22, 163, 74, 0.85)' : 'rgba(99, 102, 241, 0.75)');
        const borderColors = opts.map((_, i) => i === ansIdx ? '#16a34a' : '#4f46e5');

        quizChart.data.datasets[0].data = dataVals;
        quizChart.data.datasets[0].backgroundColor = bgColors;
        quizChart.data.datasets[0].borderColor = borderColors;
        quizChart.update();
      }
    } else {
      if (draftNotice) draftNotice.style.display = 'block';
      if (chartWrapper) chartWrapper.style.display = 'none';
    }
  }

  function getQuizFormData() {
    const qInput = document.getElementById('quizQuestionInput');
    const question = qInput.value.trim();
    const opt0 = document.getElementById('opt0').value.trim();
    const opt1 = document.getElementById('opt1').value.trim();
    const opt2 = document.getElementById('opt2').value.trim();
    const opt3 = document.getElementById('opt3').value.trim();
    const answer = parseInt(document.getElementById('quizCorrectAnswer').value, 10);
    const expInput = document.getElementById('quizExplanation');
    const explanation = expInput.value.trim();

    if (!question || !opt0 || !opt1) {
      alert('퀴즈 질문과 최소 2개 이상의 보기를 입력해 주세요.');
      return null;
    }

    return {
      id: editingQuizId || undefined,
      course: currentCourse,
      session: currentSession,
      question: question,
      options: [opt0, opt1, opt2, opt3],
      answer: answer,
      explanation: explanation
    };
  }

  function resetQuizForm() {
    document.getElementById('quizQuestionInput').value = '';
    document.getElementById('quizExplanation').value = '';
    editingQuizId = null;
    const banner = document.getElementById('editingQuizBanner');
    if (banner) banner.style.display = 'none';
  }

  // 1) 문제 임시 저장 버튼 (미공개)
  const saveDraftQuizBtn = document.getElementById('saveDraftQuizBtn');
  if (saveDraftQuizBtn) {
    saveDraftQuizBtn.addEventListener('click', () => {
      const formData = getQuizFormData();
      if (!formData) return;

      socket.emit('save_draft_quiz', formData);
      resetQuizForm();
      alert(`[${currentCourse} - ${currentSession}] 문제가 [임시 저장]되었습니다!\n학생들에게는 아직 공개되지 않으며, 원하실 때 [학생에게 공개하기] 버튼을 눌러 출제할 수 있습니다.`);
    });
  }

  // 2) 문제 즉시 출제 및 공개 버튼
  const sendQuizBtn = document.getElementById('sendQuizBtn');
  if (sendQuizBtn) {
    sendQuizBtn.addEventListener('click', () => {
      const formData = getQuizFormData();
      if (!formData) return;

      formData.is_published = true;
      socket.emit('send_quiz', formData);
      resetQuizForm();
      alert(`[${currentCourse} - ${currentSession}]에 새 퀴즈 문제가 학생들에게 즉시 출제(공개)되었습니다!`);
    });
  }

  // 3) 임시 저장 문제 -> 학생에게 공개(출제) 버튼
  const publishQuizBtn = document.getElementById('publishQuizBtn');
  if (publishQuizBtn) {
    publishQuizBtn.addEventListener('click', () => {
      if (!selectedQuizId) return;
      socket.emit('publish_quiz', { quiz_id: selectedQuizId });
      alert('선택한 문제가 학생들에게 실시간으로 공개(출제)되었습니다!');
    });
  }

  // 4) 공개된 문제 -> 비공개(임시 저장)로 전환 버튼
  const unpublishQuizBtn = document.getElementById('unpublishQuizBtn');
  if (unpublishQuizBtn) {
    unpublishQuizBtn.addEventListener('click', () => {
      if (!selectedQuizId) return;
      if (!confirm('이 문제를 비공개(임시 저장)로 전환하시겠습니까? 학생 화면에서 문제가 즉시 내려갑니다.')) return;
      socket.emit('unpublish_quiz', { quiz_id: selectedQuizId });
      alert('문제가 비공개(임시 저장)로 전환되었습니다.');
    });
  }

  // 5) 선택된 문제 내용 수정 버튼
  const editQuizBtn = document.getElementById('editSelectedQuizBtn');
  if (editQuizBtn) {
    editQuizBtn.addEventListener('click', () => {
      const sessionQuizzes = getCurrentSessionQuizzes();
      const targetQuiz = sessionQuizzes.find(q => q.id === selectedQuizId);
      if (!targetQuiz) return;

      document.getElementById('quizQuestionInput').value = targetQuiz.question || '';
      if (targetQuiz.options && targetQuiz.options.length >= 4) {
        document.getElementById('opt0').value = targetQuiz.options[0] || '';
        document.getElementById('opt1').value = targetQuiz.options[1] || '';
        document.getElementById('opt2').value = targetQuiz.options[2] || '';
        document.getElementById('opt3').value = targetQuiz.options[3] || '';
      }
      if (targetQuiz.answer !== undefined) {
        document.getElementById('quizCorrectAnswer').value = targetQuiz.answer;
      }
      document.getElementById('quizExplanation').value = targetQuiz.explanation || '';

      editingQuizId = targetQuiz.id;
      const banner = document.getElementById('editingQuizBanner');
      if (banner) banner.style.display = 'flex';

      const qIn = document.getElementById('quizQuestionInput');
      if (qIn) qIn.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  }

  // 수정 취소 버튼
  const cancelEditBtn = document.getElementById('cancelEditQuizBtn');
  if (cancelEditBtn) {
    cancelEditBtn.addEventListener('click', () => {
      resetQuizForm();
    });
  }

  // 6) 개별 문제 삭제 버튼
  const deleteQuizBtn = document.getElementById('deleteSelectedQuizBtn');
  if (deleteQuizBtn) {
    deleteQuizBtn.addEventListener('click', () => {
      if (!selectedQuizId) return;
      if (!confirm('현재 선택된 퀴즈 문제를 삭제하시겠습니까?')) return;
      socket.emit('delete_quiz', { quiz_id: selectedQuizId });
    });
  }

  // 7) 현재 차시 전체 퀴즈 출제 취소 버튼
  const cancelBtn = document.getElementById('cancel-quiz-btn');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      if (!confirm(`[${currentCourse} - ${currentSession}]의 모든 문제를 삭제/정리하시겠습니까?`)) return;
      socket.emit('cancel_quiz', { course: currentCourse, session: currentSession });
      alert(`[${currentCourse} - ${currentSession}] 퀴즈가 취소되었습니다.`);
    });
  }

  // 소켓 이벤트: 임시 저장 완료 수신
  socket.on('draft_saved', (quiz) => {
    console.log('[Professor] draft_saved:', quiz);
    if (!quiz) return;
    const exists = activeQuizzes.find(q => q.id === quiz.id);
    if (exists) {
      Object.assign(exists, quiz);
    } else {
      activeQuizzes.push(quiz);
    }
    selectedQuizId = quiz.id;
    renderProfessorQuizDashboard();
  });

  // 소켓 이벤트: 퀴즈 공개 상태 수신
  socket.on('quiz_published', (quiz) => {
    console.log('[Professor] quiz_published:', quiz);
    if (!quiz) return;
    const item = activeQuizzes.find(q => q.id === quiz.id);
    if (item) item.is_published = true;
    renderProfessorQuizDashboard();
  });

  // 소켓 이벤트: 퀴즈 비공개 상태 수신
  socket.on('quiz_unpublished', (data) => {
    console.log('[Professor] quiz_unpublished:', data);
    if (!data || !data.quiz_id) return;
    const item = activeQuizzes.find(q => q.id === data.quiz_id);
    if (item) item.is_published = false;
    renderProfessorQuizDashboard();
  });

  // 소켓 이벤트: 활성 퀴즈 전체 갱신
  socket.on('active_quizzes_updated', (data) => {
    console.log('[Professor] active_quizzes_updated:', data);
    if (!data) return;
    activeQuizzes = data.active_quizzes || [];
    if (data.quiz_stats) quizStats = data.quiz_stats;
    renderProfessorQuizDashboard();
  });

  // 소켓 이벤트: 신규 퀴즈 수신
  socket.on('quiz_added', (quiz) => {
    console.log('[Professor] quiz_added:', quiz);
    if (!quiz) return;
    const exists = activeQuizzes.find(q => q.id === quiz.id);
    if (exists) {
      Object.assign(exists, quiz);
    } else {
      activeQuizzes.push(quiz);
    }
    selectedQuizId = quiz.id;
    renderProfessorQuizDashboard();
  });

  // 소켓 이벤트: 퀴즈 삭제 수신
  socket.on('quiz_deleted', (data) => {
    console.log('[Professor] quiz_deleted:', data);
    if (!data || !data.quiz_id) return;
    activeQuizzes = activeQuizzes.filter(q => q.id !== data.quiz_id);
    delete quizStats[data.quiz_id];
    renderProfessorQuizDashboard();
  });

  // 소켓 이벤트: 실시간 통계 수신
  socket.on('update_quiz_stats', (statsData) => {
    console.log('[Professor] update_quiz_stats:', statsData);
    if (!statsData || !statsData.quiz_id) return;
    quizStats[statsData.quiz_id] = statsData;
    renderProfessorQuizDashboard();
  });

  // 소켓 이벤트: clear_quiz
  socket.on('clear_quiz', (data) => {
    console.log('[Professor] clear_quiz received:', data);
    if (data && data.course && data.session) {
      activeQuizzes = activeQuizzes.filter(q => !(q.course === data.course && q.session === data.session));
    } else {
      activeQuizzes = [];
      quizStats = {};
    }
    renderProfessorQuizDashboard();
  });

  // 10. 데이터 초기화 버튼
  const resetBtn = document.getElementById('resetDataBtn');
  resetBtn.addEventListener('click', async () => {
    if (!confirm(`[${currentCourse} - ${currentSession}] 피드백 데이터를 초기화하시겠습니까?`)) return;
    try {
      await fetch('/api/reset_opinions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ course: currentCourse, session: currentSession })
      });
      fetchGraphData();
    } catch (err) {
      console.error(err);
    }
  });

  function escapeHtml(text) {
    if (!text) return '';
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  loadInitialCourses();
});
