document.addEventListener('DOMContentLoaded', () => {
  const socket = io();
  const profConnStatus = document.getElementById('profConnStatus');

  let currentCourse = '원가회계';
  let currentSession = '1주차';
  let sessionMap = {};
  let activeQuizzes = [];
  let quizStats = {};
  let activeQuizFilter = 'ALL';

  socket.on('connect', () => {
    profConnStatus.className = 'status-badge online';
    profConnStatus.innerText = '실시간 연결됨';
    socket.emit('join_professor_room');
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

  // 1-2. 퀴즈 문제별 동적 Chart.js 인스턴스 맵 (quiz_id -> Chart)
  const quizChartsMap = {};

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
      if (typeof fetchMaterialInfo === 'function') {
        fetchMaterialInfo();
      }
      if (typeof fetchSessionReport === 'function') {
        fetchSessionReport();
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
    activeQuizFilter = 'ALL';

    updateSessionDropdown();
    fetchGraphData();
    updateCumulativeStats();
    if (typeof fetchMaterialInfo === 'function') {
      fetchMaterialInfo();
    }
    if (typeof refreshQuizzesFromServer === 'function') {
      await refreshQuizzesFromServer();
    }
    if (typeof fetchSessionReport === 'function') {
      fetchSessionReport();
    }

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
    activeQuizFilter = 'ALL';
    fetchGraphData();
    if (typeof refreshQuizzesFromServer === 'function') {
      await refreshQuizzesFromServer();
    } else if (typeof renderProfessorQuizDashboard === 'function') {
      renderProfessorQuizDashboard();
    }
    if (typeof fetchMaterialInfo === 'function') {
      fetchMaterialInfo();
    }
    if (typeof fetchSessionReport === 'function') {
      fetchSessionReport();
    }

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

  // --- 7.5. 이번 주차 수업자료(PDF/PPT) 관리 로직 ---
  const materialCourseDisplay = document.getElementById('materialCourseDisplay');
  const materialSessionDisplay = document.getElementById('materialSessionDisplay');
  const materialFileInput = document.getElementById('materialFileInput');
  const selectMaterialFileBtn = document.getElementById('selectMaterialFileBtn');
  const deleteMaterialBtn = document.getElementById('deleteMaterialBtn');
  const materialStatusText = document.getElementById('materialStatusText');
  const materialUploadProgress = document.getElementById('materialUploadProgress');

  function updateMaterialHeader() {
    if (materialCourseDisplay) materialCourseDisplay.innerText = currentCourse;
    if (materialSessionDisplay) materialSessionDisplay.innerText = currentSession;
  }

  async function fetchMaterialInfo() {
    updateMaterialHeader();
    if (!materialStatusText) return;
    try {
      const res = await fetch(`/api/material_info?course=${encodeURIComponent(currentCourse)}&session=${encodeURIComponent(currentSession)}`);
      const data = await res.json();
      if (data.has_material) {
        materialStatusText.innerHTML = `
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <span style="color: #15803d; background: #dcfce7; border: 1px solid #bbf7d0; padding: 2px 8px; border-radius: 4px; font-size: 0.78rem; font-weight: 700;">✓ 교안 등록 완료</span>
            <b style="color: #0f172a; font-size: 0.9rem;">📄 ${escapeHtml(data.filename)}</b>
            <span style="color: var(--text-muted); font-size: 0.8rem;">(총 ${data.total_units}장 분석됨 · ${data.uploaded_at})</span>
          </div>
        `;
        if (deleteMaterialBtn) deleteMaterialBtn.style.display = 'inline-flex';
        if (selectMaterialFileBtn) selectMaterialFileBtn.innerText = '🔄 교안 파일 변경';
      } else {
        materialStatusText.innerHTML = `⚠️ [${currentCourse} - ${currentSession}] 등록된 수업자료가 없습니다. PDF나 PPT 교안을 업로드하시면 AI가 직접 학습합니다.`;
        if (deleteMaterialBtn) deleteMaterialBtn.style.display = 'none';
        if (selectMaterialFileBtn) selectMaterialFileBtn.innerText = '📤 수업자료(PDF/PPT) 업로드';
      }
    } catch (e) {
      console.warn('수업자료 상태 조회 오류:', e);
    }
  }

  if (selectMaterialFileBtn && materialFileInput) {
    selectMaterialFileBtn.addEventListener('click', () => {
      materialFileInput.click();
    });

    materialFileInput.addEventListener('change', async (e) => {
      const file = e.target.files[0];
      if (!file) return;

      const formData = new FormData();
      formData.append('file', file);
      formData.append('course', currentCourse);
      formData.append('session', currentSession);

      if (materialUploadProgress) materialUploadProgress.style.display = 'inline-block';
      if (selectMaterialFileBtn) selectMaterialFileBtn.disabled = true;

      try {
        const res = await fetch('/api/upload_material', {
          method: 'POST',
          body: formData
        });
        const result = await res.json();
        if (result.success) {
          alert(`[${currentCourse} - ${currentSession}] 수업자료('${result.material.filename}')가 성공적으로 등록 및 분석되었습니다!\n이제 [AI 종합 분석 보고서 생성] 버튼을 누르면 이 교안을 바탕으로 정밀 분석이 수행됩니다.`);
          fetchMaterialInfo();
        } else {
          alert(`업로드 실패: ${result.error || '알 수 없는 오류'}`);
        }
      } catch (err) {
        alert('파일 업로드 중 오류가 발생했습니다.');
      } finally {
        if (materialUploadProgress) materialUploadProgress.style.display = 'none';
        if (selectMaterialFileBtn) selectMaterialFileBtn.disabled = false;
        materialFileInput.value = '';
      }
    });
  }

  if (deleteMaterialBtn) {
    deleteMaterialBtn.addEventListener('click', async () => {
      if (!confirm(`[${currentCourse} - ${currentSession}] 등록된 수업자료를 삭제하시겠습니까?`)) return;
      try {
        const res = await fetch('/api/delete_material', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ course: currentCourse, session: currentSession })
        });
        const result = await res.json();
        if (result.success) {
          alert('수업자료가 삭제되었습니다.');
          fetchMaterialInfo();
        }
      } catch (err) {
        console.warn('자료 삭제 오류:', err);
      }
    });
  }

  // 8. 실시간 세션 종합 분석 (수업자료 + 채점결과 + 피드백)
  const analyzeBtn = document.getElementById('analyzeOpinionsBtn');
  const analysisCard = document.getElementById('analysisResultCard');
  const analysisContent = document.getElementById('analysisContent');
  const applyQuizBtn = document.getElementById('applySuggestedQuizBtn');
  const studentReportSyncNotice = document.getElementById('studentReportSyncNotice');
  let lastSuggestedQuiz = null;

  async function fetchSessionReport() {
    if (!analysisCard || !analysisContent) return;
    try {
      const res = await fetch(`/api/session_report?course=${encodeURIComponent(currentCourse)}&session=${encodeURIComponent(currentSession)}&_t=${Date.now()}`);
      const data = await res.json();
      if (data.has_report && data.professor_report) {
        analysisCard.classList.add('active');
        analysisContent.innerText = data.professor_report;
        if (studentReportSyncNotice) {
          studentReportSyncNotice.style.display = data.student_report ? 'block' : 'none';
        }
        if (data.recommended_quiz) {
          lastSuggestedQuiz = data.recommended_quiz;
          if (applyQuizBtn) applyQuizBtn.style.display = 'inline-flex';
        } else {
          if (applyQuizBtn) applyQuizBtn.style.display = 'none';
        }
      } else {
        // 이전 주차의 분석 결과 및 채점 데이터가 새 주차에 남아있지 않도록 리셋
        analysisCard.classList.remove('active');
        analysisContent.innerText = '';
        if (applyQuizBtn) applyQuizBtn.style.display = 'none';
        if (studentReportSyncNotice) studentReportSyncNotice.style.display = 'none';
      }
    } catch (err) {
      console.warn('세션 AI 분석 보고서 조회 오류:', err);
    }
  }

  analyzeBtn.addEventListener('click', async () => {
    analyzeBtn.disabled = true;
    analyzeBtn.innerText = '수업자료·채점결과·피드백 3중 결합 분석 중... ⏳';
    analysisCard.classList.add('active');
    if (studentReportSyncNotice) studentReportSyncNotice.style.display = 'none';
    analysisContent.innerText = `[${currentCourse} - ${currentSession}] 주차별 수업자료와 퀴즈 채점 결과, 학생 피드백을 결합 분석 중입니다... 잠시만 기다려 주세요.`;

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

      if (studentReportSyncNotice) {
        if (data.student_report) {
          studentReportSyncNotice.style.display = 'block';
        } else {
          studentReportSyncNotice.style.display = 'none';
        }
      }

      if (data.recommended_quiz) {
        lastSuggestedQuiz = data.recommended_quiz;
        applyQuizBtn.style.display = 'inline-flex';
      } else {
        applyQuizBtn.style.display = 'none';
      }
      analysisCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) {
      analysisContent.innerText = '분석 도중 오류가 발생했습니다.';
    } finally {
      analyzeBtn.disabled = false;
      analyzeBtn.innerHTML = '<span>✨</span> AI 종합 분석 보고서 생성';
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
      if (!q || !q.question) return false;
      const qCourse = (q.course || '').trim();
      const qSession = (q.session || '').trim();
      if (!qCourse || !qSession) return false;
      const cMatch = (qCourse === currentCourse.trim());
      const sMatch = (currentSession === '전체' || qSession === currentSession.trim());
      return cMatch && sMatch;
    });
  }

  async function refreshQuizzesFromServer() {
    try {
      const res = await fetch(`/api/current_quiz?_t=${Date.now()}`);
      const data = await res.json();
      if (data) {
        if (data.active_quizzes) activeQuizzes = data.active_quizzes;
        if (data.quiz_stats) quizStats = data.quiz_stats;
      }
    } catch (err) {
      console.warn('퀴즈 데이터 동기화 오류:', err);
    } finally {
      if (typeof renderProfessorQuizDashboard === 'function') {
        renderProfessorQuizDashboard();
      }
    }
  }

  function renderProfessorQuizDashboard() {
    const sessionBadge = document.getElementById('quizSessionBadge');
    if (sessionBadge) {
      sessionBadge.innerText = `${currentCourse} (${currentSession})`;
    }

    const sessionQuizzes = getCurrentSessionQuizzes();
    const tabsBar = document.getElementById('quizTabsBar');
    const container = document.getElementById('quizResultsContainer');
    const noQuiz = document.getElementById('noQuizPlaceholder');

    // 1) 기존 차트 인스턴스 모두 정리
    Object.keys(quizChartsMap).forEach(id => {
      if (quizChartsMap[id]) {
        try {
          quizChartsMap[id].destroy();
        } catch (e) {
          console.warn('Chart destroy error:', e);
        }
        delete quizChartsMap[id];
      }
    });

    // 2) 출제된 퀴즈가 없는 경우
    if (sessionQuizzes.length === 0) {
      if (tabsBar) tabsBar.innerHTML = '';
      if (container) container.innerHTML = '';
      if (noQuiz) noQuiz.style.display = 'block';
      return;
    }

    if (noQuiz) noQuiz.style.display = 'none';

    // 3) 상단 필터 / 바로가기 탭 바 렌더링
    if (tabsBar) {
      tabsBar.innerHTML = '';

      // [📋 전체 동시 보기] 버튼
      const allBtn = document.createElement('button');
      allBtn.type = 'button';
      const isAllActive = (activeQuizFilter === 'ALL');
      allBtn.className = `quiz-tab-btn ${isAllActive ? 'active' : ''}`;
      allBtn.style.cssText = `padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 700; cursor: pointer; transition: all 0.2s; border: 1px solid ${isAllActive ? '#4f46e5' : '#cbd5e1'}; background: ${isAllActive ? '#4f46e5' : '#ffffff'}; color: ${isAllActive ? '#ffffff' : '#334155'}; white-space: nowrap;`;
      allBtn.innerHTML = `📋 전체 동시 보기 (${sessionQuizzes.length}문제)`;
      allBtn.addEventListener('click', () => {
        activeQuizFilter = 'ALL';
        renderProfessorQuizDashboard();
      });
      tabsBar.appendChild(allBtn);

      // 각 문제별 탭 버튼
      sessionQuizzes.forEach((q, idx) => {
        const stat = quizStats[q.id];
        const count = (stat && stat.total_responses) || 0;
        const btn = document.createElement('button');
        btn.type = 'button';
        const isSelected = (activeQuizFilter === q.id);
        const isPub = (q.is_published === true);
        btn.className = `quiz-tab-btn ${isSelected ? 'active' : ''}`;
        btn.style.cssText = `padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; cursor: pointer; transition: all 0.2s; border: 1px solid ${isSelected ? '#4f46e5' : '#cbd5e1'}; background: ${isSelected ? '#4f46e5' : '#ffffff'}; color: ${isSelected ? '#ffffff' : '#334155'}; white-space: nowrap;`;

        const badgeHtml = isPub
          ? `<span id="tabBadge_${q.id}" style="background:${isSelected ? 'rgba(255,255,255,0.3)' : '#dcfce7'}; color:${isSelected ? '#ffffff' : '#15803d'}; padding: 1px 5px; border-radius: 4px; font-size: 0.72rem; margin-left: 3px; font-weight: 700;">공개 ${count}명</span>`
          : `<span id="tabBadge_${q.id}" style="background:${isSelected ? 'rgba(255,255,255,0.3)' : '#fef3c7'}; color:${isSelected ? '#ffffff' : '#b45309'}; padding: 1px 5px; border-radius: 4px; font-size: 0.72rem; margin-left: 3px; font-weight: 700;">🔒임시</span>`;

        btn.innerHTML = `문제 ${idx + 1} ${badgeHtml}`;
        btn.addEventListener('click', () => {
          activeQuizFilter = q.id;
          renderProfessorQuizDashboard();
          const targetCard = document.getElementById(`quizCard_${q.id}`);
          if (targetCard) {
            targetCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }
        });
        tabsBar.appendChild(btn);
      });
    }

    // 4) 표시할 퀴즈 목록 결정 (ALL 이면 전체 동시 표시)
    let quizzesToDisplay = (activeQuizFilter === 'ALL')
      ? sessionQuizzes
      : sessionQuizzes.filter(q => q.id === activeQuizFilter);

    if (quizzesToDisplay.length === 0) {
      activeQuizFilter = 'ALL';
      quizzesToDisplay = sessionQuizzes;
    }

    // 5) 문제별 카드 HTML 렌더링
    if (!container) return;
    container.innerHTML = '';

    quizzesToDisplay.forEach((q) => {
      const globalIdx = sessionQuizzes.indexOf(q) + 1;
      const isPub = (q.is_published === true);
      const stat = quizStats[q.id] || { total_responses: 0, stats: {} };
      const count = stat.total_responses || 0;
      const ansIdx = parseInt(q.answer, 10);
      const ansText = (q.options && q.options[ansIdx]) ? escapeHtml(q.options[ansIdx]) : '';
      const ansPreview = ansText.length > 25 ? ansText.substring(0, 25) + '…' : ansText;

      const card = document.createElement('div');
      card.className = 'card quiz-card';
      card.id = `quizCard_${q.id}`;
      card.style.cssText = `border: 1px solid ${isPub ? '#e2e8f0' : '#fef3c7'}; background: ${isPub ? '#ffffff' : '#fffdfa'}; border-radius: 8px; padding: 0.85rem; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 0.25rem;`;

      card.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.6rem; border-bottom: 1px solid #f1f5f9; padding-bottom: 0.5rem;">
          <div style="flex: 1; min-width: 200px;">
            <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px; flex-wrap: wrap;">
              <span style="background: #e0e7ff; color: #3730a3; padding: 2px 7px; border-radius: 4px; font-size: 0.78rem; font-weight: 700;">문제 ${globalIdx}</span>
              ${isPub
                ? `<span style="background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; font-size: 0.75rem; font-weight: 700; padding: 2px 7px; border-radius: 4px;">🟢 공개 중</span>`
                : `<span style="background: #fef3c7; color: #b45309; border: 1px solid #fde68a; font-size: 0.75rem; font-weight: 700; padding: 2px 7px; border-radius: 4px;">🔒 임시 저장 (미공개)</span>`
              }
              <div style="font-size: 0.92rem; font-weight: 700; color: #0f172a; line-height: 1.3;">${escapeHtml(q.question)}</div>
            </div>
            <div style="font-size: 0.8rem; color: var(--text-muted); display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
              <span>총 응답: <b id="quizResponseCount_${q.id}" style="color: var(--primary); font-size: 0.9rem;">${count}</b>명</span>
              <span>정답: <b style="color: #16a34a; font-weight: 700;">보기 ${ansIdx + 1}${ansPreview ? ': ' + ansPreview : ''}</b></span>
            </div>
          </div>

          <div style="display: flex; gap: 0.35rem; align-items: center; flex-wrap: wrap;">
            ${isPub
              ? `<button type="button" class="btn btn-unpublish-quiz" style="background: #d97706; color: #ffffff; padding: 0.25rem 0.65rem; font-size: 0.78rem; font-weight: 700;">🔒 비공개로 전환</button>`
              : `<button type="button" class="btn btn-publish-quiz" style="background: #16a34a; color: #ffffff; padding: 0.25rem 0.65rem; font-size: 0.78rem; font-weight: 700;">🚀 학생에게 공개하기</button>`
            }
            <button type="button" class="btn btn-edit-quiz" style="background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; padding: 0.25rem 0.6rem; font-size: 0.78rem;">✏️ 내용 수정</button>
            <button type="button" class="btn btn-delete-quiz" style="background: #fee2e2; color: #b91c1c; border: 1px solid #fecaca; padding: 0.25rem 0.6rem; font-size: 0.78rem;">🗑️ 삭제</button>
          </div>
        </div>

        ${isPub
          ? `<div style="height: 175px; position: relative;">
               <canvas id="quizChart_${q.id}"></canvas>
             </div>`
          : `<div style="text-align: center; background: #fffbeb; border: 1px dashed #fcd34d; border-radius: 6px; padding: 1.25rem 0.75rem; color: #92400e; font-size: 0.85rem;">
               <div style="font-size: 1.3rem; margin-bottom: 0.2rem;">🔒</div>
               <b>아직 학생들에게 공개되지 않은 [임시 저장] 문제입니다.</b><br>
               우측 상단의 <b>[🚀 학생에게 공개하기]</b> 버튼을 누르면 학생 화면에 실시간으로 출제되며 응답 차트가 활성화됩니다.
             </div>`
        }
      `;

      // 버튼 이벤트 바인딩
      const pubBtn = card.querySelector('.btn-publish-quiz');
      if (pubBtn) {
        pubBtn.addEventListener('click', () => {
          socket.emit('publish_quiz', { quiz_id: q.id });
          alert(`[문제 ${globalIdx}]가 학생들에게 실시간으로 공개(출제)되었습니다!`);
        });
      }

      const unpubBtn = card.querySelector('.btn-unpublish-quiz');
      if (unpubBtn) {
        unpubBtn.addEventListener('click', () => {
          if (!confirm(`[문제 ${globalIdx}]를 비공개(임시 저장)로 전환하시겠습니까? 학생 화면에서 문제가 즉시 내려갑니다.`)) return;
          socket.emit('unpublish_quiz', { quiz_id: q.id });
          alert(`[문제 ${globalIdx}]가 비공개(임시 저장)로 전환되었습니다.`);
        });
      }

      const editBtn = card.querySelector('.btn-edit-quiz');
      if (editBtn) {
        editBtn.addEventListener('click', () => {
          document.getElementById('quizQuestionInput').value = q.question || '';
          if (q.options && q.options.length >= 4) {
            document.getElementById('opt0').value = q.options[0] || '';
            document.getElementById('opt1').value = q.options[1] || '';
            document.getElementById('opt2').value = q.options[2] || '';
            document.getElementById('opt3').value = q.options[3] || '';
          }
          if (q.answer !== undefined) {
            document.getElementById('quizCorrectAnswer').value = q.answer;
          }
          document.getElementById('quizExplanation').value = q.explanation || '';

          editingQuizId = q.id;
          const banner = document.getElementById('editingQuizBanner');
          if (banner) banner.style.display = 'flex';

          const qIn = document.getElementById('quizQuestionInput');
          if (qIn) qIn.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
      }

      const delBtn = card.querySelector('.btn-delete-quiz');
      if (delBtn) {
        delBtn.addEventListener('click', () => {
          if (!confirm(`[문제 ${globalIdx}] 퀴즈 문제를 정말 삭제하시겠습니까?`)) return;
          socket.emit('delete_quiz', { quiz_id: q.id });
        });
      }

      container.appendChild(card);

      // 6) 공개된 문제인 경우 독립적인 Chart.js 인스턴스 생성
      if (isPub) {
        const canvasEl = document.getElementById(`quizChart_${q.id}`);
        if (canvasEl) {
          const ctx = canvasEl.getContext('2d');
          const opts = q.options || ['보기 1', '보기 2', '보기 3', '보기 4'];
          const labels = opts.map((opt, i) => {
            const short = opt.length > 15 ? opt.substring(0, 15) + '…' : opt;
            return `보기 ${i + 1}: ${short}`;
          });
          const sMap = stat.stats || {};
          const dataVals = opts.map((_, i) => sMap[i] || 0);
          const bgColors = opts.map((_, i) => i === ansIdx ? 'rgba(22, 163, 74, 0.85)' : 'rgba(99, 102, 241, 0.75)');
          const borderColors = opts.map((_, i) => i === ansIdx ? '#16a34a' : '#4f46e5');

          quizChartsMap[q.id] = new Chart(ctx, {
            type: 'bar',
            data: {
              labels: labels,
              datasets: [{
                label: '응답자 수',
                data: dataVals,
                backgroundColor: bgColors,
                borderColor: borderColors,
                borderWidth: 1.5,
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
        }
      }
    });
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

  // 수정 취소 버튼
  const cancelEditBtn = document.getElementById('cancelEditQuizBtn');
  if (cancelEditBtn) {
    cancelEditBtn.addEventListener('click', () => {
      resetQuizForm();
    });
  }

  // 3) 현재 차시 전체 퀴즈 출제 취소 버튼
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
    renderProfessorQuizDashboard();
  });

  // 소켓 이벤트: 퀴즈 삭제 수신
  socket.on('quiz_deleted', (data) => {
    console.log('[Professor] quiz_deleted:', data);
    if (!data || !data.quiz_id) return;
    activeQuizzes = activeQuizzes.filter(q => q.id !== data.quiz_id);
    delete quizStats[data.quiz_id];
    if (activeQuizFilter === data.quiz_id) {
      activeQuizFilter = 'ALL';
    }
    renderProfessorQuizDashboard();
  });

  // 소켓 이벤트: 실시간 개별 문제 통계 수신 (동시 화면 차트 즉시 갱신)
  socket.on('update_quiz_stats', (statsData) => {
    console.log('[Professor] update_quiz_stats:', statsData);
    if (!statsData || !statsData.quiz_id) return;
    quizStats[statsData.quiz_id] = statsData;

    // 1) 해당 문제 카드의 응답자 수 즉각 갱신
    const countEl = document.getElementById(`quizResponseCount_${statsData.quiz_id}`);
    if (countEl) {
      countEl.innerText = statsData.total_responses || 0;
    }

    // 2) 탭 바의 뱃지 갱신
    const tabBadgeEl = document.getElementById(`tabBadge_${statsData.quiz_id}`);
    if (tabBadgeEl) {
      tabBadgeEl.innerText = `공개 ${statsData.total_responses || 0}명`;
    }

    // 3) 해당 문제의 막대그래프 차트 데이터 즉각 애니메이션 갱신
    const chart = quizChartsMap[statsData.quiz_id];
    if (chart && chart.data) {
      const q = activeQuizzes.find(item => item.id === statsData.quiz_id);
      const opts = (q && q.options) || ['보기 1', '보기 2', '보기 3', '보기 4'];
      const sMap = statsData.stats || {};
      chart.data.datasets[0].data = opts.map((_, i) => sMap[i] || 0);
      chart.update();
    } else {
      renderProfessorQuizDashboard();
    }
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
