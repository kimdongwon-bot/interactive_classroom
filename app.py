import os
import json
import datetime
import threading
import uuid
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
from dotenv import load_dotenv
from ai_tutor import ai_tutor

# .env 환경 변수 로드
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-teaching-app-secret-key-2528')
app.config['PERMANENT_SESSION_LIFETIME'] = datetime.timedelta(days=30)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60, ping_interval=25)

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

from material_parser import extract_text_from_file

PROFESSOR_PIN = os.getenv('PROFESSOR_PIN', '2528')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DATA_FILE = os.path.join(DATA_DIR, 'history.json')
BACKUP_FILE = os.path.join(DATA_DIR, 'history.json.bak')
MATERIALS_DIR = os.path.join(DATA_DIR, 'materials')
data_lock = threading.Lock()

CATEGORY_KEYS = ["이해 완료", "조금 어려움", "질문 있음", "예제 필요"]
DEFAULT_COURSES = ["원가회계", "회계감사", "캡스톤디자인(ESG공시)"]

def init_default_data():
    return {
        "active_course": "원가회계",
        "active_session": "1주차",
        "courses": {
            c: {
                "sessions": ["1주차", "2주차", "3주차"],
                "opinions": [],
                "quizzes": []
            }
            for c in DEFAULT_COURSES
        }
    }

# 인메모리 마스터 캐시 및 스레드 락 기반 안전 동기화
server_data_cache = None

def _persist_data_to_disk_unlocked(data):
    """디스크에 원자적으로 안전하게 저장 및 백업 생성 (락 내부에서 호출)"""
    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)

        # 1. 기존 유효 파일 백업 유지
        if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
            try:
                import shutil
                shutil.copy2(DATA_FILE, BACKUP_FILE)
            except Exception as e:
                print(f"백업 복사 실패: {e}")

        # 2. 임시 파일로 먼저 쓴 뒤 os.replace로 원자적 교체 (동시 읽기 시 빈 파일/충돌 방지)
        temp_file = os.path.join(DATA_DIR, f"history.tmp.{uuid.uuid4().hex[:6]}")
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, DATA_FILE)
    except Exception as e:
        print(f"디스크 원자적 저장 실패, 직접 쓰기 시도: {e}")
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e2:
            print(f"직접 저장 오류: {e2}")

def _init_server_data_cache():
    global server_data_cache
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

    # 1. DATA_FILE 읽기 시도
    if os.path.exists(DATA_FILE) and os.path.getsize(DATA_FILE) > 0:
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data and "courses" in data and data["courses"]:
                    server_data_cache = data
                    return
        except Exception as e:
            print(f"history.json 파싱 오류: {e}, 백업 복구 시도...")

    # 2. BACKUP_FILE 읽기 시도
    if os.path.exists(BACKUP_FILE) and os.path.getsize(BACKUP_FILE) > 0:
        try:
            with open(BACKUP_FILE, 'r', encoding='utf-8') as bf:
                data = json.load(bf)
                if data and "courses" in data and data["courses"]:
                    print("[*] history.json.bak 백업에서 정상 복구 완료!")
                    server_data_cache = data
                    _persist_data_to_disk_unlocked(server_data_cache)
                    return
        except Exception as be:
            print(f"history.json.bak 읽기 오류: {be}")

    # 3. 기본값 초기화 (기존 파일이 없을 때만)
    server_data_cache = init_default_data()
    _persist_data_to_disk_unlocked(server_data_cache)

def load_data():
    """인메모리 캐시에서 최신 데이터를 안전하게 반환 (읽기 전용 복사본)"""
    global server_data_cache
    with data_lock:
        if server_data_cache is None:
            _init_server_data_cache()
        import copy
        return copy.deepcopy(server_data_cache)

def save_data(data):
    """전체 데이터 갱신 및 디스크 영구 저장 (기존 데이터 절대 유실 방지)"""
    global server_data_cache
    with data_lock:
        server_data_cache = data
        _persist_data_to_disk_unlocked(server_data_cache)
    sync_quizzes_from_storage()

# 활성 퀴즈 상태 (인메모리 다중 퀴즈 및 문제별 통계 지원)
active_quiz = None
active_quizzes = []  # list of quiz dicts
quiz_answers_by_id = {}  # quiz_id -> list of selected_options

def sync_quizzes_from_storage():
    """서버 시작 시 또는 복구 시 영구 저장소에서 퀴즈 목록 및 응답 통계 동기화"""
    global active_quizzes, active_quiz, quiz_answers_by_id
    try:
        data = load_data()
        loaded = []
        new_answers = {}
        for c, cdata in data.get("courses", {}).items():
            for q in cdata.get("quizzes", []):
                q["course"] = c
                if not q.get("session"):
                    q["session"] = "1주차"
                if "is_published" not in q:
                    q["is_published"] = False
                if "answers" in q:
                    new_answers[q.get("id")] = list(q.get("answers", []))
                elif q.get("id") in quiz_answers_by_id:
                    new_answers[q.get("id")] = quiz_answers_by_id[q.get("id")]
                if not any(item.get("id") == q.get("id") for item in loaded):
                    loaded.append(q)
        active_quizzes = loaded
        quiz_answers_by_id = new_answers
        pub = [q for q in active_quizzes if q.get("is_published")]
        active_quiz = pub[-1] if pub else None
    except Exception as e:
        print(f"퀴즈 로드 중 오류: {e}")

def save_quiz_to_storage(quiz):
    """퀴즈 객체를 history.json의 해당 과목 퀴즈 목록에 저장/갱신 (타 과목 고스트 레코드 정리 및 기존 answers 보존)"""
    try:
        data = load_data()
        course = (quiz.get("course") or "").strip() or "원가회계"
        session_val = (quiz.get("session") or "").strip()
        if not session_val:
            print(f"퀴즈 저장 거부: session 값이 비어있습니다. (id: {quiz.get('id')})")
            return False

        quiz["course"] = course
        quiz["session"] = session_val
        quiz_id = quiz.get("id")

        # 1) 타 과목에 남아있는 동일 ID 고스트 레코드 완벽 정리
        for c, cdata in data.get("courses", {}).items():
            if c != course:
                cdata["quizzes"] = [q for q in cdata.get("quizzes", []) if q.get("id") != quiz_id]

        # 2) 대상 과목에 저장/갱신 (기존 answers 보존)
        if course in data.get("courses", {}):
            q_list = data["courses"][course].setdefault("quizzes", [])
            idx = next((i for i, q in enumerate(q_list) if q.get("id") == quiz_id), -1)
            if idx >= 0:
                if "answers" not in quiz and "answers" in q_list[idx]:
                    quiz["answers"] = q_list[idx]["answers"]
                q_list[idx] = quiz
            else:
                q_list.append(quiz)
            save_data(data)
    except Exception as e:
        print(f"퀴즈 저장 오류: {e}")

def remove_quiz_from_storage(quiz_id):
    """특정 퀴즈 ID를 history.json에서 삭제"""
    try:
        data = load_data()
        changed = False
        for c, cdata in data.get("courses", {}).items():
            before = len(cdata.get("quizzes", []))
            cdata["quizzes"] = [q for q in cdata.get("quizzes", []) if q.get("id") != quiz_id]
            if len(cdata["quizzes"]) != before:
                changed = True
        if changed:
            save_data(data)
    except Exception as e:
        print(f"퀴즈 삭제 저장 오류: {e}")

def remove_course_session_quizzes_from_storage(course=None, session=None):
    """지정된 과목/세션의 퀴즈 전체를 history.json에서 삭제"""
    try:
        data = load_data()
        changed = False
        for c, cdata in data.get("courses", {}).items():
            if course and c != course:
                continue
            if session:
                before = len(cdata.get("quizzes", []))
                cdata["quizzes"] = [q for q in cdata.get("quizzes", []) if q.get("session") != session]
                if len(cdata["quizzes"]) != before:
                    changed = True
            else:
                cdata["quizzes"] = []
                changed = True
        if changed:
            save_data(data)
    except Exception as e:
        print(f"차시 퀴즈 일괄 삭제 저장 오류: {e}")

# 초기 구동 시 영구 저장소의 퀴즈 불러오기
sync_quizzes_from_storage()

def get_quiz_stats_dict(quiz_id):
    """특정 퀴즈 ID의 응답 통계 반환"""
    quiz = next((q for q in active_quizzes if q.get("id") == quiz_id), None)
    answers = quiz_answers_by_id.get(quiz_id, [])
    options_len = len(quiz.get("options", [])) if quiz else 4
    stats = {i: answers.count(i) for i in range(options_len)}
    return {
        "quiz_id": quiz_id,
        "total_responses": len(answers),
        "stats": stats,
        "correct_index": quiz.get("answer") if quiz else None,
        "is_published": quiz.get("is_published", False) if quiz else False
    }

def get_all_quiz_stats():
    """모든 활성 퀴즈의 통계 맵 반환"""
    return {q.get("id"): get_quiz_stats_dict(q.get("id")) for q in active_quizzes if q.get("id")}

def sanitize_quiz_for_student(quiz_dict):
    """학생용 퀴즈 데이터 정제: 정답(answer), 해설(explanation), 전체 제출답안(answers) 은폐"""
    if not quiz_dict or not isinstance(quiz_dict, dict):
        return quiz_dict
    clean = dict(quiz_dict)
    clean.pop("answer", None)
    clean.pop("explanation", None)
    clean.pop("answers", None)
    return clean

def sanitize_quizzes_for_student(quiz_list):
    """학생용 퀴즈 목록 정제"""
    if not quiz_list:
        return []
    return [sanitize_quiz_for_student(q) for q in quiz_list]

def sanitize_quiz_stats_for_student(stats_map):
    """학생용 퀴즈 통계 정제: correct_index 은폐"""
    if not stats_map:
        return {}
    clean = {}
    for qid, stat in stats_map.items():
        if isinstance(stat, dict):
            c_stat = dict(stat)
            c_stat.pop("correct_index", None)
            clean[qid] = c_stat
        else:
            clean[qid] = stat
    return clean

def _compute_graph_data_from_dict(data, target_course=None, target_session=None):
    course = target_course or data.get("active_course", "원가회계")
    session_name = target_session or data.get("active_session", "1주차")

    course_obj = data["courses"].get(course, {"sessions": [], "opinions": []})
    all_opinions = course_obj.get("opinions", [])

    # 세션 필터링 ("전체"인 경우 해당 과목의 모든 세션 합산)
    if session_name == "전체":
        filtered_opinions = all_opinions
    else:
        filtered_opinions = [op for op in all_opinions if op.get("session") == session_name]

    counts = [sum(1 for op in filtered_opinions if op.get("category") == k) for k in CATEGORY_KEYS]

    # 주차별 누적 이해도 변화 추이 계산 (전체 세션별 통계)
    session_trend = {}
    for sess in course_obj.get("sessions", []):
        sess_ops = [op for op in all_opinions if op.get("session") == sess]
        session_trend[sess] = {
            "total": len(sess_ops),
            "counts": {k: sum(1 for op in sess_ops if op.get("category") == k) for k in CATEGORY_KEYS}
        }

    return {
        "course": course,
        "session": session_name,
        "available_courses": list(data["courses"].keys()),
        "available_sessions": course_obj.get("sessions", []),
        "labels": CATEGORY_KEYS,
        "counts": counts,
        "total": len(filtered_opinions),
        "cumulative_total": len(all_opinions),
        "recent_opinions": filtered_opinions[-20:][::-1],
        "session_trend": session_trend
    }

def get_graph_data(target_course=None, target_session=None):
    """지정된 과목 및 세션(강의시간)의 차트 데이터 및 누적 통계 반환"""
    data = load_data()
    return _compute_graph_data_from_dict(data, target_course, target_session)

# ================= HTTP 라우트 =================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login_professor', methods=['POST'])
def login_professor():
    req_data = request.get_json(silent=True) or request.form
    entered_pin = str(req_data.get('pin', '')).strip()

    if entered_pin == PROFESSOR_PIN:
        session.permanent = True
        session['is_professor'] = True
        return jsonify({"success": True, "redirect": url_for('professor')})
    else:
        return jsonify({"success": False, "message": "PIN 번호가 올바르지 않습니다."}), 401

@app.route('/student')
def student():
    return render_template('student.html')

@app.route('/professor')
def professor():
    if not session.get('is_professor'):
        return redirect(url_for('index', error='unauthorized'))
    return render_template('professor.html')

@app.route('/logout_professor', methods=['GET', 'POST'])
def logout_professor():
    session.pop('is_professor', None)
    return redirect(url_for('index'))

# --- 과목 및 강의시간 관리 API ---

@app.route('/api/courses', methods=['GET'])
def api_get_courses():
    sync_quizzes_from_storage()
    data = load_data()
    session_map = {c: data["courses"][c].get("sessions", []) for c in data["courses"]}
    active_session_map = {
        c: data["courses"][c].get("active_session") or (data["courses"][c].get("sessions", ["1주차"])[0] if data["courses"][c].get("sessions") else "1주차")
        for c in data["courses"]
    }
    is_prof = session.get('is_professor', False)
    filtered_quizzes = active_quizzes if is_prof else [q for q in active_quizzes if q.get("is_published", True)]
    curr_quiz = active_quiz if (is_prof or (active_quiz and active_quiz.get("is_published", True))) else (filtered_quizzes[-1] if filtered_quizzes else None)
    quiz_stats = get_all_quiz_stats() if is_prof else sanitize_quiz_stats_for_student(get_all_quiz_stats())
    if not is_prof:
        filtered_quizzes = sanitize_quizzes_for_student(filtered_quizzes)
        curr_quiz = sanitize_quiz_for_student(curr_quiz)

    active_c = data.get("active_course", "원가회계")
    active_s = data["courses"].get(active_c, {}).get("active_session") or data.get("active_session", "1주차")

    return jsonify({
        "active_course": active_c,
        "active_session": active_s,
        "courses": list(data["courses"].keys()),
        "session_map": session_map,
        "active_session_map": active_session_map,
        "active_quiz": curr_quiz,
        "active_quizzes": filtered_quizzes,
        "quiz_stats": quiz_stats
    })

@app.route('/api/current_quiz', methods=['GET'])
def api_get_current_quiz():
    sync_quizzes_from_storage()
    data = load_data()
    is_prof = session.get('is_professor', False)

    req_course = request.args.get('course', '').strip()
    req_session = request.args.get('session', '').strip()

    filtered_quizzes = active_quizzes if is_prof else [q for q in active_quizzes if q.get("is_published", True)]

    # 서버 사이드 과목 및 차시(주차) 필터링 지원
    if req_course:
        filtered_quizzes = [q for q in filtered_quizzes if (q.get("course") or "").strip() == req_course]
    if req_session and req_session != '전체':
        filtered_quizzes = [q for q in filtered_quizzes if (q.get("session") or "").strip() == req_session]

    curr_quiz = active_quiz if (is_prof or (active_quiz and active_quiz.get("is_published", True))) else (filtered_quizzes[-1] if filtered_quizzes else None)
    if curr_quiz and req_course and (curr_quiz.get("course") or "").strip() != req_course:
        curr_quiz = filtered_quizzes[-1] if filtered_quizzes else None
    if curr_quiz and req_session and req_session != '전체' and (curr_quiz.get("session") or "").strip() != req_session:
        curr_quiz = filtered_quizzes[-1] if filtered_quizzes else None

    quiz_stats = get_all_quiz_stats() if is_prof else sanitize_quiz_stats_for_student(get_all_quiz_stats())
    if not is_prof:
        filtered_quizzes = sanitize_quizzes_for_student(filtered_quizzes)
        curr_quiz = sanitize_quiz_for_student(curr_quiz)

    active_c = req_course or data.get("active_course", "원가회계")
    active_s = req_session if (req_session and req_session != '전체') else (data["courses"].get(active_c, {}).get("active_session") or data.get("active_session", "1주차"))

    return jsonify({
        "active_quiz": curr_quiz,
        "active_quizzes": filtered_quizzes,
        "quiz_stats": quiz_stats,
        "active_course": active_c,
        "active_session": active_s
    })

@app.route('/api/set_active_session', methods=['POST'])
def api_set_active_session():
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    new_course = req_data.get('course')
    new_session = req_data.get('session')

    data = load_data()
    if new_course and new_course in data["courses"]:
        data["active_course"] = new_course
        if new_session:
            data["courses"][new_course]["active_session"] = new_session
            data["active_session"] = new_session
    elif new_session:
        data["active_session"] = new_session
        curr_c = data.get("active_course", "원가회계")
        if curr_c in data.get("courses", {}):
            data["courses"][curr_c]["active_session"] = new_session

    save_data(data)
    graph_data = get_graph_data(data["active_course"], data["active_session"])
    socketio.emit('update_graph', graph_data)
    socketio.emit('session_changed', {
        "active_course": data["active_course"],
        "active_session": data["active_session"]
    })
    return jsonify({"success": True, "active_course": data["active_course"], "active_session": data["active_session"]})

@app.route('/api/add_session', methods=['POST'])
def api_add_session():
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    target_course = req_data.get('course')
    new_session_name = (req_data.get('session_name') or '').strip()

    if not target_course or not new_session_name:
        return jsonify({"success": False, "message": "과목과 강의시간명을 입력해 주세요."}), 400

    data = load_data()
    if target_course not in data["courses"]:
        return jsonify({"success": False, "message": "존재하지 않는 과목입니다."}), 404

    sessions = data["courses"][target_course].setdefault("sessions", [])
    if new_session_name not in sessions:
        sessions.append(new_session_name)
        data["active_course"] = target_course
        data["active_session"] = new_session_name
        save_data(data)

    return jsonify({"success": True, "sessions": sessions, "active_session": new_session_name})

@app.route('/api/add_course', methods=['POST'])
def api_add_course():
    """교수 권한: 새로운 과목 추가"""
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    new_course_name = (req_data.get('course_name') or req_data.get('course') or '').strip()

    if not new_course_name:
        return jsonify({"success": False, "message": "추가할 과목명을 입력해 주세요."}), 400

    data = load_data()
    if new_course_name in data["courses"]:
        return jsonify({"success": False, "message": f"이미 존재하는 과목명('{new_course_name}')입니다."}), 400

    # 신규 과목 초기 차시(1~3주차) 및 빈 피드백 목록 등록
    data["courses"][new_course_name] = {
        "sessions": ["1주차", "2주차", "3주차"],
        "opinions": [],
        "quizzes": []
    }
    save_data(data)

    session_map = {c: data["courses"][c].get("sessions", []) for c in data["courses"]}
    socketio.emit('courses_updated', {
        "courses": list(data["courses"].keys()),
        "session_map": session_map,
        "active_course": data.get("active_course"),
        "active_session": data.get("active_session"),
        "added": new_course_name
    })

    return jsonify({
        "success": True,
        "courses": list(data["courses"].keys()),
        "course_name": new_course_name,
        "session_map": session_map
    })

@app.route('/api/rename_course', methods=['POST'])
def api_rename_course():
    """교수 권한: 기존 과목명 수정 및 누적 데이터 승계"""
    global active_quiz
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    old_name = (req_data.get('old_name') or req_data.get('old_course') or '').strip()
    new_name = (req_data.get('new_name') or req_data.get('new_course') or '').strip()

    if not old_name or not new_name:
        return jsonify({"success": False, "message": "기존 과목명과 변경할 과목명을 모두 입력해 주세요."}), 400

    data = load_data()
    if old_name not in data["courses"]:
        return jsonify({"success": False, "message": f"과목 '{old_name}'이(가) 존재하지 않습니다."}), 404

    if old_name != new_name and new_name in data["courses"]:
        return jsonify({"success": False, "message": f"이미 존재하는 과목명('{new_name}')입니다."}), 400

    if old_name != new_name:
        # 기존 순서 보존하면서 키 변경 및 피드백 데이터 승계
        new_courses = {}
        for k, v in data["courses"].items():
            if k == old_name:
                for op in v.get("opinions", []):
                    op["course"] = new_name
                new_courses[new_name] = v
            else:
                new_courses[k] = v
        data["courses"] = new_courses

        # 현재 활성 과목이 변경된 대상인 경우 동기화
        active_changed = False
        if data.get("active_course") == old_name:
            data["active_course"] = new_name
            active_changed = True

        # 활성 퀴즈들의 과목명도 연동
        for q in active_quizzes:
            if q.get("course") == old_name:
                q["course"] = new_name
        if active_quiz and active_quiz.get("course") == old_name:
            active_quiz["course"] = new_name

        save_data(data)

        session_map = {c: data["courses"][c].get("sessions", []) for c in data["courses"]}
        socketio.emit('courses_updated', {
            "courses": list(data["courses"].keys()),
            "session_map": session_map,
            "active_course": data.get("active_course"),
            "active_session": data.get("active_session"),
            "renamed": {"old_name": old_name, "new_name": new_name}
        })
        if active_changed:
            socketio.emit('session_changed', {
                "active_course": data["active_course"],
                "active_session": data["active_session"]
            })

    session_map = {c: data["courses"][c].get("sessions", []) for c in data["courses"]}
    return jsonify({
        "success": True,
        "courses": list(data["courses"].keys()),
        "old_name": old_name,
        "new_name": new_name,
        "session_map": session_map
    })

@app.route('/api/delete_course', methods=['POST'])
def api_delete_course():
    """교수 권한: 과목 삭제 (최소 1개 이상 유지 필수)"""
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    target_course = (req_data.get('course') or req_data.get('course_name') or '').strip()

    data = load_data()
    if target_course not in data["courses"]:
        return jsonify({"success": False, "message": "존재하지 않는 과목입니다."}), 404

    if len(data["courses"]) <= 1:
        return jsonify({"success": False, "message": "최소 1개 이상의 과목이 유지되어야 합니다."}), 400

    del data["courses"][target_course]

    active_changed = False
    if data.get("active_course") == target_course:
        first_course = next(iter(data["courses"].keys()))
        data["active_course"] = first_course
        sessions = data["courses"][first_course].get("sessions", [])
        data["active_session"] = sessions[0] if sessions else "1주차"
        active_changed = True

    save_data(data)

    session_map = {c: data["courses"][c].get("sessions", []) for c in data["courses"]}
    socketio.emit('courses_updated', {
        "courses": list(data["courses"].keys()),
        "session_map": session_map,
        "active_course": data.get("active_course"),
        "active_session": data.get("active_session"),
        "deleted": target_course
    })
    if active_changed:
        socketio.emit('session_changed', {
            "active_course": data["active_course"],
            "active_session": data["active_session"]
        })

    return jsonify({
        "success": True,
        "courses": list(data["courses"].keys()),
        "active_course": data.get("active_course"),
        "session_map": session_map
    })

@app.route('/api/graph_data', methods=['GET'])
def api_get_graph_data():
    course = request.args.get('course')
    sess = request.args.get('session')
    return jsonify(get_graph_data(course, sess))

# --- 수업자료(PDF/PPT) 관리 API ---

@app.route('/api/upload_material', methods=['POST'])
def api_upload_material():
    """교수자: 특정 과목 및 주차(세션)의 수업자료(PDF, PPTX) 업로드 및 텍스트 추출 저장"""
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    if 'file' not in request.files:
        return jsonify({"error": "업로드된 파일이 없습니다."}), 400

    file = request.files['file']
    course = request.form.get('course', '원가회계')
    sess = request.form.get('session', '1주차')

    if not file.filename:
        return jsonify({"error": "선택된 파일명이 없습니다."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.pdf', '.pptx', '.ppt', '.txt', '.md']:
        return jsonify({"error": f"지원되지 않는 파일 형식입니다 ({ext}). PDF 또는 PPTX 파일을 업로드해 주세요."}), 400

    try:
        os.makedirs(MATERIALS_DIR, exist_ok=True)
        # 안전한 파일명 생성
        safe_fname = f"{uuid.uuid4().hex[:6]}_{file.filename}"
        saved_path = os.path.join(MATERIALS_DIR, safe_fname)
        file.save(saved_path)

        # 텍스트 및 슬라이드 구조 추출
        parse_res = extract_text_from_file(saved_path)
        if not parse_res.get("success"):
            if os.path.exists(saved_path):
                try:
                    os.remove(saved_path)
                except Exception:
                    pass
            return jsonify({"error": parse_res.get("error", "자료 텍스트 추출 실패")}), 400

        data = load_data()
        # 기존에 업로드된 이전 파일이 있다면 디스크에서 정리
        old_mat = data.get("courses", {}).get(course, {}).get("materials", {}).get(sess, {})
        old_saved_file = old_mat.get("saved_file")
        if old_saved_file:
            old_path = os.path.join(MATERIALS_DIR, old_saved_file)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass

        mat_data = {
            "filename": file.filename,
            "saved_file": safe_fname,
            "file_type": parse_res.get("file_type", ext[1:]),
            "total_units": parse_res.get("total_units", 1),
            "summary_snippet": parse_res.get("summary_snippet", ""),
            "full_text": parse_res.get("full_text", ""),
            "uploaded_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        if course in data.get("courses", {}):
            data["courses"][course].setdefault("materials", {})[sess] = mat_data
            save_data(data)

        return jsonify({
            "success": True,
            "material": {
                "filename": mat_data["filename"],
                "file_type": mat_data["file_type"],
                "total_units": mat_data["total_units"],
                "uploaded_at": mat_data["uploaded_at"]
            }
        })
    except Exception as e:
        return jsonify({"error": f"파일 저장 중 오류가 발생했습니다: {str(e)}"}), 500

@app.route('/api/material_info', methods=['GET'])
def api_get_material_info():
    """현재 선택된 과목 및 세션의 수업자료 등록 정보 조회"""
    course = request.args.get('course', '원가회계')
    sess = request.args.get('session', '1주차')
    data = load_data()
    mat = data.get("courses", {}).get(course, {}).get("materials", {}).get(sess)
    if mat:
        return jsonify({
            "has_material": True,
            "filename": mat.get("filename"),
            "file_type": mat.get("file_type"),
            "total_units": mat.get("total_units"),
            "uploaded_at": mat.get("uploaded_at"),
            "summary_snippet": mat.get("summary_snippet", "")[:300]
        })
    return jsonify({"has_material": False})

@app.route('/api/delete_material', methods=['POST'])
def api_delete_material():
    """현재 선택된 과목 및 세션의 등록된 수업자료 삭제 및 디스크 정리"""
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    course = req_data.get('course', '원가회계')
    sess = req_data.get('session', '1주차')

    data = load_data()
    if course in data.get("courses", {}) and "materials" in data["courses"][course]:
        if sess in data["courses"][course]["materials"]:
            old_mat = data["courses"][course]["materials"][sess]
            old_saved_file = old_mat.get("saved_file")
            if old_saved_file:
                old_path = os.path.join(MATERIALS_DIR, old_saved_file)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
            del data["courses"][course]["materials"][sess]
            save_data(data)

    return jsonify({"success": True})

@app.route('/api/analyze_opinions', methods=['POST'])
def api_analyze_opinions():
    """현재 선택된 과목 및 세션의 종합 분석 (수업자료 + 퀴즈 채점결과 + 실시간 피드백)"""
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    data = load_data()
    course = req_data.get('course') or data.get('active_course', '원가회계')
    sess = req_data.get('session') or data.get('active_session', '1주차')

    # 1. 실시간 의견 피드백 수집 (해당 세션의 모든 실제 학생 피드백 전달)
    course_obj = data.get("courses", {}).get(course, {"sessions": [], "opinions": []})
    all_ops = course_obj.get("opinions", [])
    if sess == "전체":
        opinions = all_ops
    else:
        opinions = [op for op in all_ops if op.get("session") == sess]

    # 2. 수업자료(PDF/PPT) 내용 조회
    mat_data = data.get("courses", {}).get(course, {}).get("materials", {}).get(sess, {})

    # 3. 해당 주차 퀴즈 및 상세 채점 결과(선택지별 학생 분포) 수집
    quizzes_data = []
    course_quizzes = data.get("courses", {}).get(course, {}).get("quizzes", [])
    for q in course_quizzes:
        q_session = q.get("session", "1주차")
        if sess == "전체" or q_session == sess:
            q_id = q.get("id")
            stats_info = get_quiz_stats_dict(q_id)
            quizzes_data.append({
                "id": q_id,
                "question": q.get("question"),
                "options": q.get("options", []),
                "answer": q.get("answer", 0),
                "explanation": q.get("explanation", ""),
                "is_published": q.get("is_published", False),
                "total_responses": stats_info.get("total_responses", 0),
                "stats": stats_info.get("stats", {})
            })

    # 4. 3중 결합 AI 정밀 분석 실행 (교수용 + 학생 자가학습용 동시 도출)
    analysis = ai_tutor.analyze_session_comprehensive(
        course_name=course,
        session_name=sess,
        material_data=mat_data,
        quizzes_data=quizzes_data,
        opinions=opinions
    )

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prof_report = analysis.get("analysis_raw", "")
    student_report = analysis.get("student_report", "")

    # 5. 과목 및 차시별 보고서 영구 저장
    data = load_data()
    if course in data.get("courses", {}):
        data["courses"][course].setdefault("reports", {})[sess] = {
            "professor_report": prof_report,
            "student_report": student_report,
            "recommended_quiz": analysis.get("recommended_quiz"),
            "created_at": now_str
        }
        save_data(data)

    # 6. 학생 화면으로 자가학습 보고서 실시간 브로드캐스트
    if student_report:
        socketio.emit('student_report_updated', {
            "course": course,
            "session": sess,
            "student_report": student_report,
            "created_at": now_str
        })

    return jsonify(analysis)

@app.route('/api/student_report', methods=['GET'])
def api_get_student_report():
    """학생 화면: 현재 선택된 과목 및 세션의 자가학습 맞춤형 AI 보고서 조회"""
    course = request.args.get('course', '원가회계')
    sess = request.args.get('session', '1주차')
    data = load_data()
    report_obj = data.get("courses", {}).get(course, {}).get("reports", {}).get(sess)
    if report_obj and report_obj.get("student_report"):
        return jsonify({
            "has_report": True,
            "course": course,
            "session": sess,
            "student_report": report_obj.get("student_report"),
            "created_at": report_obj.get("created_at")
        })
    return jsonify({
        "has_report": False,
        "course": course,
        "session": sess
    })

@app.route('/api/session_report', methods=['GET'])
@app.route('/api/professor_report', methods=['GET'])
def api_get_session_report():
    """교수 화면: 특정 과목 및 세션의 기 생성된 AI 종합 분석 보고서 조회"""
    course = request.args.get('course', '원가회계')
    sess = request.args.get('session', '1주차')
    data = load_data()
    report_obj = data.get("courses", {}).get(course, {}).get("reports", {}).get(sess)
    if report_obj and report_obj.get("professor_report"):
        return jsonify({
            "has_report": True,
            "course": course,
            "session": sess,
            "professor_report": report_obj.get("professor_report"),
            "student_report": report_obj.get("student_report", ""),
            "recommended_quiz": report_obj.get("recommended_quiz"),
            "created_at": report_obj.get("created_at")
        })
    return jsonify({
        "has_report": False,
        "course": course,
        "session": sess,
        "professor_report": "",
        "student_report": ""
    })

@app.route('/api/analyze_cumulative', methods=['POST'])
def api_analyze_cumulative():
    """과목별 누적 전체 데이터(모든 주차 피드백) 종합 진단 및 해석"""
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    target_course = req_data.get('course')

    data = load_data()
    course = target_course or data.get("active_course", "원가회계")
    course_obj = data["courses"].get(course, {"sessions": [], "opinions": []})

    analysis_res = ai_tutor.analyze_cumulative_data(course, course_obj)
    return jsonify(analysis_res)

@app.route('/api/reset_opinions', methods=['POST'])
def api_reset_opinions():
    """교수 모드: 선택된 과목의 현재 세션(또는 전체) 의견 초기화"""
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    target_course = req_data.get('course')
    target_session = req_data.get('session')

    data = load_data()
    course = target_course or data.get("active_course", "원가회계")
    sess = target_session or data.get("active_session", "1주차")

    if course in data["courses"]:
        if sess == "전체":
            data["courses"][course]["opinions"] = []
        else:
            data["courses"][course]["opinions"] = [
                op for op in data["courses"][course].get("opinions", [])
                if op.get("session") != sess
            ]
        save_data(data)

    socketio.emit('update_graph', get_graph_data(course, sess))
    return jsonify({"success": True})

# ================= Socket.IO 이벤트 =================

@socketio.on('connect')
def handle_connect():
    sync_quizzes_from_storage()
    emit('update_graph', get_graph_data())
    is_prof = session.get('is_professor', False)
    if is_prof:
        join_room('professors')
    else:
        join_room('students')

    quizzes_to_send = active_quizzes if is_prof else sanitize_quizzes_for_student([q for q in active_quizzes if q.get("is_published", True)])
    stats_to_send = get_all_quiz_stats() if is_prof else sanitize_quiz_stats_for_student(get_all_quiz_stats())
    emit('active_quizzes_updated', {
        "active_quizzes": quizzes_to_send,
        "quiz_stats": stats_to_send
    })
    curr = active_quiz if (is_prof or (active_quiz and active_quiz.get("is_published", True))) else (quizzes_to_send[-1] if quizzes_to_send else None)
    if curr:
        curr_to_send = curr if is_prof else sanitize_quiz_for_student(curr)
        emit('receive_quiz', curr_to_send)
        emit('send_quiz', curr_to_send)

@socketio.on('join_professor_room')
def handle_join_professor_room():
    if session.get('is_professor'):
        join_room('professors')

@socketio.on('submit_opinion')
def handle_submit_opinion(data):
    """학생의 의견/이해도 제출 -> 해당 과목 및 세션에 영구 누적 저장 (스레드 락 기반 동시성 보장)"""
    global server_data_cache
    with data_lock:
        if server_data_cache is None:
            _init_server_data_cache()

        course = data.get('course') or server_data_cache.get('active_course', '원가회계')
        session_name = data.get('session') or server_data_cache.get('active_session', '1주차')
        category = data.get('category', '이해 완료')
        text = (data.get('text') or '').strip()

        if category not in CATEGORY_KEYS:
            category = "이해 완료"

        if course not in server_data_cache["courses"]:
            server_data_cache["courses"][course] = {"sessions": [session_name], "opinions": [], "quizzes": []}

        course_obj = server_data_cache["courses"][course]
        new_opinion = {
            "id": len(course_obj.get("opinions", [])) + 1,
            "course": course,
            "session": session_name,
            "category": category,
            "text": text if text else f"[{category}] 피드백을 전달했습니다.",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        course_obj.setdefault("opinions", []).append(new_opinion)
        _persist_data_to_disk_unlocked(server_data_cache)

        graph_data = _compute_graph_data_from_dict(server_data_cache, course, session_name)

    # 갱신된 그래프 데이터를 브로드캐스트
    emit('update_graph', graph_data, broadcast=True)
    emit('opinion_submitted_ack', {"success": True, "id": new_opinion["id"]})

@socketio.on('chat_message')
def handle_chat_message(data):
    """학생 ↔ AI 조교: 학생이 선택한 과목 맥락을 반영하여 질문 전달"""
    user_msg = data.get('message', '').strip()
    course = data.get('course', '원가회계')

    if not user_msg:
        emit('chat_response', {'response': '질문 내용을 입력해주세요.'})
        return

    # 과목 맥락을 프롬프트에 추가
    context_msg = f"[수강 과목: {course}] {user_msg}"
    bot_reply = ai_tutor.ask(context_msg)
    emit('chat_response', {'response': bot_reply, 'user_message': user_msg, 'course': course})

@socketio.on('send_quiz')
def handle_send_quiz(data):
    """교수가 학생들에게 실시간 퀴즈 출제 (즉시 공개 또는 임시 저장)"""
    if not session.get('is_professor'):
        return

    global active_quiz, active_quizzes, quiz_answers_by_id
    quiz_id = data.get("id") or f"quiz_{int(datetime.datetime.now().timestamp()*1000)}_{uuid.uuid4().hex[:4]}"
    is_pub = data.get("is_published", True)
    course = (data.get("course") or "").strip() or "원가회계"
    session_val = (data.get("session") or "").strip()
    if not session_val or session_val == '전체':
        emit('quiz_error', {"message": "출제 주차(차시)를 정확히 선택해 주세요."})
        return

    new_quiz = {
        "id": quiz_id,
        "course": course,
        "session": session_val,
        "question": data.get("question", ""),
        "options": data.get("options", []),
        "answer": data.get("answer", 0),
        "explanation": data.get("explanation", ""),
        "is_published": is_pub,
        "created_at": datetime.datetime.now().strftime("%H:%M:%S")
    }

    existing_idx = next((i for i, q in enumerate(active_quizzes) if q.get("id") == quiz_id), -1)
    if existing_idx >= 0:
        existing = active_quizzes[existing_idx]
        if "answers" in existing:
            new_quiz["answers"] = existing["answers"]
        active_quizzes[existing_idx] = new_quiz
    else:
        active_quizzes.append(new_quiz)
        quiz_answers_by_id.setdefault(quiz_id, [])

    if is_pub:
        active_quiz = new_quiz

    save_quiz_to_storage(new_quiz)

    if is_pub:
        emit('quiz_added', new_quiz, to='professors')
        sanitized_quiz = sanitize_quiz_for_student(new_quiz)
        emit('quiz_added', sanitized_quiz, to='students')
        emit('receive_quiz', sanitized_quiz, to='students')
        emit('send_quiz', sanitized_quiz, to='students')

    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, to='professors')

    emit('active_quizzes_updated', {
        "active_quizzes": sanitize_quizzes_for_student([q for q in active_quizzes if q.get("is_published", True)]),
        "quiz_stats": sanitize_quiz_stats_for_student(get_all_quiz_stats())
    }, to='students')

@socketio.on('save_draft_quiz')
def handle_save_draft_quiz(data):
    """교수가 문제를 학생에게 공개하지 않고 임시 저장"""
    if not session.get('is_professor'):
        return

    global active_quizzes, quiz_answers_by_id
    quiz_id = data.get("id") or f"quiz_{int(datetime.datetime.now().timestamp()*1000)}_{uuid.uuid4().hex[:4]}"
    course = (data.get("course") or "").strip() or "원가회계"
    session_val = (data.get("session") or "").strip()
    if not session_val or session_val == '전체':
        emit('quiz_error', {"message": "임시 저장할 주차(차시)를 정확히 선택해 주세요."})
        return

    draft_quiz = {
        "id": quiz_id,
        "course": course,
        "session": session_val,
        "question": data.get("question", ""),
        "options": data.get("options", []),
        "answer": data.get("answer", 0),
        "explanation": data.get("explanation", ""),
        "is_published": False,
        "created_at": datetime.datetime.now().strftime("%H:%M:%S")
    }

    existing_idx = next((i for i, q in enumerate(active_quizzes) if q.get("id") == quiz_id), -1)
    if existing_idx >= 0:
        existing = active_quizzes[existing_idx]
        if "answers" in existing:
            draft_quiz["answers"] = existing["answers"]
        active_quizzes[existing_idx] = draft_quiz
    else:
        active_quizzes.append(draft_quiz)
        quiz_answers_by_id.setdefault(quiz_id, [])

    save_quiz_to_storage(draft_quiz)

    emit('draft_saved', draft_quiz, to='professors')
    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, to='professors')

@socketio.on('publish_quiz')
def handle_publish_quiz(data):
    """교수가 임시 저장된 퀴즈를 학생들에게 공개(출제)"""
    if not session.get('is_professor'):
        return

    global active_quiz, active_quizzes
    quiz_id = data.get("quiz_id") if isinstance(data, dict) else str(data)
    quiz = next((q for q in active_quizzes if q.get("id") == quiz_id), None)
    if not quiz:
        return

    quiz["is_published"] = True
    active_quiz = quiz
    save_quiz_to_storage(quiz)

    emit('quiz_published', quiz, to='professors')
    emit('quiz_added', quiz, to='professors')

    sanitized = sanitize_quiz_for_student(quiz)
    emit('quiz_added', sanitized, to='students')
    emit('receive_quiz', sanitized, to='students')
    emit('send_quiz', sanitized, to='students')

    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, to='professors')

    emit('active_quizzes_updated', {
        "active_quizzes": sanitize_quizzes_for_student([q for q in active_quizzes if q.get("is_published", True)]),
        "quiz_stats": sanitize_quiz_stats_for_student(get_all_quiz_stats())
    }, to='students')

@socketio.on('unpublish_quiz')
def handle_unpublish_quiz(data):
    """교수가 공개된 퀴즈를 다시 비공개(임시 저장)로 전환"""
    if not session.get('is_professor'):
        return

    global active_quiz, active_quizzes
    quiz_id = data.get("quiz_id") if isinstance(data, dict) else str(data)
    quiz = next((q for q in active_quizzes if q.get("id") == quiz_id), None)
    if not quiz:
        return

    quiz["is_published"] = False
    save_quiz_to_storage(quiz)

    pub_left = [q for q in active_quizzes if q.get("is_published")]
    active_quiz = pub_left[-1] if pub_left else None

    emit('quiz_unpublished', {"quiz_id": quiz_id}, broadcast=True)
    emit('quiz_deleted', {"quiz_id": quiz_id}, broadcast=True)

    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, to='professors')

    emit('active_quizzes_updated', {
        "active_quizzes": sanitize_quizzes_for_student([q for q in active_quizzes if q.get("is_published", True)]),
        "quiz_stats": sanitize_quiz_stats_for_student(get_all_quiz_stats())
    }, to='students')

@socketio.on('update_quiz')
def handle_update_quiz(data):
    """교수가 퀴즈 내용(과목, 차시, 질문, 보기, 정답, 해설)을 수정"""
    if not session.get('is_professor'):
        return

    global active_quiz, active_quizzes
    quiz_id = data.get("id") or data.get("quiz_id")
    quiz = next((q for q in active_quizzes if q.get("id") == quiz_id), None)
    if not quiz:
        return

    if "course" in data and str(data["course"]).strip():
        quiz["course"] = str(data["course"]).strip()
    if "session" in data and str(data["session"]).strip():
        s_val = str(data["session"]).strip()
        if s_val and s_val != '전체':
            quiz["session"] = s_val
    if "question" in data:
        quiz["question"] = data.get("question", "")
    if "options" in data:
        quiz["options"] = data.get("options", [])
    if "answer" in data:
        quiz["answer"] = data.get("answer", 0)
    if "explanation" in data:
        quiz["explanation"] = data.get("explanation", "")
    if "is_published" in data:
        quiz["is_published"] = data["is_published"]

    save_quiz_to_storage(quiz)

    if quiz.get("is_published"):
        active_quiz = quiz
        emit('quiz_added', quiz, to='professors')
        emit('quiz_added', sanitize_quiz_for_student(quiz), to='students')

    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, to='professors')

    emit('active_quizzes_updated', {
        "active_quizzes": sanitize_quizzes_for_student([q for q in active_quizzes if q.get("is_published", True)]),
        "quiz_stats": sanitize_quiz_stats_for_student(get_all_quiz_stats())
    }, to='students')

@socketio.on('delete_quiz')
def handle_delete_quiz(data):
    """교수가 특정 퀴즈 문제를 선택 삭제"""
    if not session.get('is_professor'):
        return

    global active_quiz, active_quizzes, quiz_answers_by_id
    quiz_id = data.get("quiz_id") if isinstance(data, dict) else str(data)
    active_quizzes = [q for q in active_quizzes if q.get("id") != quiz_id]
    quiz_answers_by_id.pop(quiz_id, None)
    pub_left = [q for q in active_quizzes if q.get("is_published")]
    active_quiz = pub_left[-1] if pub_left else None
    remove_quiz_from_storage(quiz_id)

    emit('quiz_deleted', {"quiz_id": quiz_id}, broadcast=True)

    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, to='professors')

    emit('active_quizzes_updated', {
        "active_quizzes": sanitize_quizzes_for_student([q for q in active_quizzes if q.get("is_published", True)]),
        "quiz_stats": sanitize_quiz_stats_for_student(get_all_quiz_stats())
    }, to='students')

@socketio.on('cancel_quiz')
def handle_cancel_quiz(data=None):
    """교수가 출제된 실시간 퀴즈를 취소하고 학생 화면에서 숨김 (차시별 또는 전체)"""
    if not session.get('is_professor'):
        return

    global active_quiz, active_quizzes, quiz_answers_by_id
    req = data if isinstance(data, dict) else {}
    target_course = req.get("course")
    target_session = req.get("session")

    if target_course and target_session:
        removed_ids = [q["id"] for q in active_quizzes if q.get("course") == target_course and q.get("session") == target_session]
        active_quizzes = [q for q in active_quizzes if not (q.get("course") == target_course and q.get("session") == target_session)]
        for qid in removed_ids:
            quiz_answers_by_id.pop(qid, None)
        remove_course_session_quizzes_from_storage(target_course, target_session)
    else:
        active_quizzes = []
        quiz_answers_by_id = {}
        remove_course_session_quizzes_from_storage()

    pub_left = [q for q in active_quizzes if q.get("is_published")]
    active_quiz = pub_left[-1] if pub_left else None
    emit('clear_quiz', {"course": target_course, "session": target_session}, broadcast=True)

    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, to='professors')

    emit('active_quizzes_updated', {
        "active_quizzes": sanitize_quizzes_for_student([q for q in active_quizzes if q.get("is_published", True)]),
        "quiz_stats": sanitize_quiz_stats_for_student(get_all_quiz_stats())
    }, to='students')

@socketio.on('submit_quiz_answer')
def handle_submit_quiz_answer(data):
    """학생의 퀴즈 답안 제출 -> 서버 사이드 자동 채점, 학생에게 결과 전송, 통계 영구 저장 및 교수 화면 갱신"""
    global quiz_answers_by_id
    quiz_id = data.get("quiz_id")
    c = data.get("course")
    s = data.get("session")

    # quiz_id가 없을 경우 동일 과목/주차 내의 퀴즈만 탐색 (전체 active_quizzes[-1] 폴백 금지)
    if not quiz_id and c and s:
        matched = [q for q in active_quizzes if q.get("course") == c and q.get("session") == s]
        if matched:
            quiz_id = matched[-1]["id"]

    if not quiz_id:
        return

    # 유효한 퀴즈 탐색
    quiz = next((q for q in active_quizzes if q.get("id") == quiz_id), None)
    if not quiz:
        try:
            storage = load_data()
            for cname, cdata in storage.get("courses", {}).items():
                for q in cdata.get("quizzes", []):
                    if q.get("id") == quiz_id:
                        quiz = q
                        break
                if quiz:
                    break
        except Exception:
            pass

    if not quiz:
        return

    selected = data.get("selected_option")
    if selected is None:
        return

    try:
        selected_idx = int(selected)
    except (ValueError, TypeError):
        return

    try:
        correct_ans = int(quiz.get("answer", 0))
    except (ValueError, TypeError):
        correct_ans = 0

    is_correct = (selected_idx == correct_ans)
    explanation = quiz.get("explanation", "")

    # 학생에게 채점 결과 전송
    emit('quiz_answer_result', {
        "quiz_id": quiz_id,
        "is_correct": is_correct,
        "selected_option": selected_idx,
        "correct_answer": correct_ans,
        "explanation": explanation
    })

    if quiz_id not in quiz_answers_by_id:
        quiz_answers_by_id[quiz_id] = []
    quiz_answers_by_id[quiz_id].append(selected_idx)

    # 영구 저장소의 퀴즈 데이터에도 답안 동기화
    try:
        storage = load_data()
        for cname, cdata in storage.get("courses", {}).items():
            for q in cdata.get("quizzes", []):
                if q.get("id") == quiz_id:
                    q.setdefault("answers", []).append(selected_idx)
                    save_data(storage)
                    break
    except Exception as e:
        print(f"답안 영구 저장 오류: {e}")

    stats_info = get_quiz_stats_dict(quiz_id)
    emit('update_quiz_stats', stats_info, to='professors')

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"[*] 실시간 소통 및 AI 학습 웹앱 서버 가동 시작: http://localhost:{port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
