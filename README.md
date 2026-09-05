# Interactive Classroom (실시간 강의 소통 및 AI 학습 지원 웹앱)

대학 강의 및 실시간 수업에서 교수자와 학생 간의 쌍방향 소통을 극대화하고, Google Gemini AI를 활용하여 수업 피드백 분석 및 맞춤형 퀴즈 출제를 지원하는 웹 애플리케이션입니다.

---

## 🌟 주요 기능

### 1. ⚡ 실시간 다중 퀴즈 출제 & 청중 응답 통계
- **다중 퀴즈 연속 출제**: 동일 차시 내에서 여러 개의 퀴즈(4지선다)를 연속해서 출제 가능
- **실시간 응답 집계**: 문제별 탭 전환을 통해 출제된 문제별 응답자 수 및 선택지 분포 차트(Chart.js) 실시간 모니터링
- **학생 개별 풀이 & 해설**: 학생 화면에서 출제된 문제 카드별로 독립적으로 응답 제출 및 정답/해설 즉시 확인

### 2. 📡 실시간 수업 모니터링 & 학생 의견 수집
- 학생들의 이해도(이해 완료, 조금 어려움, 질문 있음, 예제 필요) 실시간 차트 시각화
- 학생들이 남긴 질문 및 피드백 실시간 피드 스트림

### 3. 🤖 Google Gemini AI 기반 강의 분석 & 맞춤 퀴즈 추천
- **실시간 세션 분석**: 현재 차시에 수집된 학생 의견을 AI가 분석하여 수업 개선점 및 추천 퀴즈 제시
- **원클릭 퀴즈 자동 완성**: AI 추천 퀴즈를 출제 폼에 원클릭으로 자동 입력 후 즉시 출제

### 4. 📊 과목별 누적 분석 & AI 종합 진단
- 학기 전체 주차별 이해도 추이 변화 그래프
- 누적 데이터를 바탕으로 한 취약 단원 분석 및 장기적 강의 개선 AI 종합 진단서 생성

### 5. 🔒 과목 및 차시별 완벽한 데이터 격리 & 교수 보안 인증
- 교수 전용 PIN 이중 인증 보안
- 과목 추가/수정/삭제 및 강의시간(차시) 동적 관리

---

## 🚀 빠른 시작 가이드

### 1. 환경 설정 및 패키지 설치
\\ash
# 가상환경 생성 및 활성화
python -m venv venv
# Windows:
venv\Scriptsctivate
# Linux/Mac:
source venv/bin/activate

# 의존성 패키지 설치
pip install -r requirements.txt
\
### 2. 환경 변수 설정 (.env)
\.env.example\ 파일을 복사하여 \.env\를 생성하고 API 키를 설정합니다:
\\ash
cp .env.example .env
\
### 3. 서버 실행
\\ash
python app.py
\브라우저에서 \http://localhost:5000\으로 접속합니다:
- **학생 화면**: \http://localhost:5000/student- **교수 화면**: \http://localhost:5000/professor\ (기본 PIN: ª8\)

---

## 📁 프로젝트 구조

\\	ext
├── app.py                  # Flask 및 Socket.IO 백엔드 서버
├── ai_tutor.py             # Google Gemini AI 연동 모듈
├── requirements.txt        # 파이썬 의존성 패키지 목록
├── .env.example            # 환경 변수 예시 파일
├── .gitignore              # Git 제외 파일 설정 (.env, venv 등)
├── data/
│   └── history.json        # 과목/차시/피드백 로컬 데이터 저장소
├── static/
│   ├── professor.js        # 교수 대시보드 클라이언트 로직
│   ├── student.js          # 학생 화면 클라이언트 로직
│   └── style.css           # 전체 UI 스타일시트
├── templates/
│   ├── index.html          # 메인 진입 페이지 (학생/교수 선택)
│   ├── professor.html      # 교수 전용 대시보드 뷰
│   └── student.html        # 학생 전용 인터랙티브 뷰
└── test_e2e.py             # 전체 기능 엔드투엔드(E2E) 자동화 테스트
\