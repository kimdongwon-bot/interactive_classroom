import os
import json
import datetime
import threading
import uuid
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit
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

PROFESSOR_PIN = os.getenv('PROFESSOR_PIN', '2528')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DATA_FILE = os.path.join(DATA_DIR, 'history.json')
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

def load_data():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        data = init_default_data()
        save_data(data)
        return data

    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 기본 과목 누락 방지: courses가 비어있는 경우에만 기본 과목 생성
            if "courses" not in data or not data["courses"]:
                data["courses"] = {
                    c: {"sessions": ["1주차", "2주차", "3주차"], "opinions": [], "quizzes": []}
                    for c in DEFAULT_COURSES
                }
            return data
    except Exception as e:
        print(f"데이터 파일 읽기 오류: {e}, 기본값으로 복구합니다.")
        data = init_default_data()
        save_data(data)
        return data

def save_data(data):
    with data_lock:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR, exist_ok=True)
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

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
        for c, cdata in data.get("courses", {}).items():
            for q in cdata.get("quizzes", []):
                q.setdefault("course", c)
                q.setdefault("is_published", False)
                if "answers" in q:
                    quiz_answers_by_id[q.get("id")] = list(q.get("answers", []))
                if not any(item.get("id") == q.get("id") for item in loaded):
                    loaded.append(q)
        active_quizzes = loaded
        pub = [q for q in active_quizzes if q.get("is_published")]
        active_quiz = pub[-1] if pub else None
    except Exception as e:
        print(f"퀴즈 로드 중 오류: {e}")

def save_quiz_to_storage(quiz):
    """퀴즈 객체를 history.json의 해당 과목 퀴즈 목록에 저장/갱신"""
    try:
        data = load_data()
        course = quiz.get("course", "원가회계")
        if course in data.get("courses", {}):
            q_list = data["courses"][course].setdefault("quizzes", [])
            idx = next((i for i, q in enumerate(q_list) if q.get("id") == quiz.get("id")), -1)
            if idx >= 0:
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

def get_graph_data(target_course=None, target_session=None):
    """지정된 과목 및 세션(강의시간)의 차트 데이터 및 누적 통계 반환"""
    data = load_data()
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
        return jsonify({"success": False, "message": "PIN 번호가 올바르지 않습니다. (기본: 2528)"}), 401

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
    data = load_data()
    session_map = {c: data["courses"][c].get("sessions", []) for c in data["courses"]}
    is_prof = session.get('is_professor', False)
    filtered_quizzes = active_quizzes if is_prof else [q for q in active_quizzes if q.get("is_published", True)]
    curr_quiz = active_quiz if (is_prof or (active_quiz and active_quiz.get("is_published", True))) else (filtered_quizzes[-1] if filtered_quizzes else None)
    return jsonify({
        "active_course": data.get("active_course", "원가회계"),
        "active_session": data.get("active_session", "1주차"),
        "courses": list(data["courses"].keys()),
        "session_map": session_map,
        "active_quiz": curr_quiz,
        "active_quizzes": filtered_quizzes,
        "quiz_stats": get_all_quiz_stats()
    })

@app.route('/api/current_quiz', methods=['GET'])
def api_get_current_quiz():
    data = load_data()
    is_prof = session.get('is_professor', False)
    filtered_quizzes = active_quizzes if is_prof else [q for q in active_quizzes if q.get("is_published", True)]
    curr_quiz = active_quiz if (is_prof or (active_quiz and active_quiz.get("is_published", True))) else (filtered_quizzes[-1] if filtered_quizzes else None)
    return jsonify({
        "active_quiz": curr_quiz,
        "active_quizzes": filtered_quizzes,
        "quiz_stats": get_all_quiz_stats(),
        "active_course": data.get("active_course", "원가회계"),
        "active_session": data.get("active_session", "1주차")
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
        data["active_session"] = new_session

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

@app.route('/api/analyze_opinions', methods=['POST'])
def api_analyze_opinions():
    """현재 선택된 과목 및 세션의 의견 분석"""
    if not session.get('is_professor'):
        return jsonify({"error": "Unauthorized"}), 401

    req_data = request.get_json(silent=True) or {}
    course = req_data.get('course')
    sess = req_data.get('session')

    graph_data = get_graph_data(course, sess)
    opinions = graph_data.get("recent_opinions", [])
    analysis = ai_tutor.analyze_opinions(opinions)
    return jsonify(analysis)

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
    emit('update_graph', get_graph_data())
    is_prof = session.get('is_professor', False)
    quizzes_to_send = active_quizzes if is_prof else [q for q in active_quizzes if q.get("is_published", True)]
    emit('active_quizzes_updated', {
        "active_quizzes": quizzes_to_send,
        "quiz_stats": get_all_quiz_stats()
    })
    curr = active_quiz if (is_prof or (active_quiz and active_quiz.get("is_published", True))) else (quizzes_to_send[-1] if quizzes_to_send else None)
    if curr:
        emit('receive_quiz', curr)
        emit('send_quiz', curr)

@socketio.on('submit_opinion')
def handle_submit_opinion(data):
    """학생의 의견/이해도 제출 -> 해당 과목 및 세션에 영구 누적 저장"""
    storage = load_data()

    course = data.get('course') or storage.get('active_course', '원가회계')
    session_name = data.get('session') or storage.get('active_session', '1주차')
    category = data.get('category', '이해 완료')
    text = (data.get('text') or '').strip()

    if category not in CATEGORY_KEYS:
        category = "이해 완료"

    if course not in storage["courses"]:
        storage["courses"][course] = {"sessions": [session_name], "opinions": [], "quizzes": []}

    course_obj = storage["courses"][course]
    new_opinion = {
        "id": len(course_obj.get("opinions", [])) + 1,
        "course": course,
        "session": session_name,
        "category": category,
        "text": text if text else f"[{category}] 피드백을 전달했습니다.",
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    course_obj.setdefault("opinions", []).append(new_opinion)
    save_data(storage)

    # 갱신된 그래프 데이터를 브로드캐스트
    emit('update_graph', get_graph_data(course, session_name), broadcast=True)
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
    global active_quiz, active_quizzes, quiz_answers_by_id
    quiz_id = data.get("id") or f"quiz_{int(datetime.datetime.now().timestamp()*1000)}_{uuid.uuid4().hex[:4]}"
    is_pub = data.get("is_published", True)
    new_quiz = {
        "id": quiz_id,
        "course": data.get("course", "원가회계"),
        "session": data.get("session", "1주차"),
        "question": data.get("question", ""),
        "options": data.get("options", []),
        "answer": data.get("answer", 0),
        "explanation": data.get("explanation", ""),
        "is_published": is_pub,
        "created_at": datetime.datetime.now().strftime("%H:%M:%S")
    }

    existing_idx = next((i for i, q in enumerate(active_quizzes) if q.get("id") == quiz_id), -1)
    if existing_idx >= 0:
        active_quizzes[existing_idx] = new_quiz
    else:
        active_quizzes.append(new_quiz)
        quiz_answers_by_id.setdefault(quiz_id, [])

    if is_pub:
        active_quiz = new_quiz

    save_quiz_to_storage(new_quiz)

    if is_pub:
        emit('quiz_added', new_quiz, broadcast=True)
        emit('receive_quiz', new_quiz, broadcast=True)
        emit('send_quiz', new_quiz, broadcast=True)

    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, broadcast=True)

@socketio.on('save_draft_quiz')
def handle_save_draft_quiz(data):
    """교수가 문제를 학생에게 공개하지 않고 임시 저장"""
    global active_quizzes, quiz_answers_by_id
    quiz_id = data.get("id") or f"quiz_{int(datetime.datetime.now().timestamp()*1000)}_{uuid.uuid4().hex[:4]}"
    draft_quiz = {
        "id": quiz_id,
        "course": data.get("course", "원가회계"),
        "session": data.get("session", "1주차"),
        "question": data.get("question", ""),
        "options": data.get("options", []),
        "answer": data.get("answer", 0),
        "explanation": data.get("explanation", ""),
        "is_published": False,
        "created_at": datetime.datetime.now().strftime("%H:%M:%S")
    }

    existing_idx = next((i for i, q in enumerate(active_quizzes) if q.get("id") == quiz_id), -1)
    if existing_idx >= 0:
        active_quizzes[existing_idx] = draft_quiz
    else:
        active_quizzes.append(draft_quiz)
        quiz_answers_by_id.setdefault(quiz_id, [])

    save_quiz_to_storage(draft_quiz)

    emit('draft_saved', draft_quiz)
    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, broadcast=True)

@socketio.on('publish_quiz')
def handle_publish_quiz(data):
    """교수가 임시 저장된 퀴즈를 학생들에게 공개(출제)"""
    global active_quiz, active_quizzes
    quiz_id = data.get("quiz_id") if isinstance(data, dict) else str(data)
    quiz = next((q for q in active_quizzes if q.get("id") == quiz_id), None)
    if not quiz:
        return

    quiz["is_published"] = True
    active_quiz = quiz
    save_quiz_to_storage(quiz)

    emit('quiz_published', quiz, broadcast=True)
    emit('quiz_added', quiz, broadcast=True)
    emit('receive_quiz', quiz, broadcast=True)
    emit('send_quiz', quiz, broadcast=True)
    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, broadcast=True)

@socketio.on('unpublish_quiz')
def handle_unpublish_quiz(data):
    """교수가 공개된 퀴즈를 다시 비공개(임시 저장)로 전환"""
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
    }, broadcast=True)

@socketio.on('update_quiz')
def handle_update_quiz(data):
    """교수가 퀴즈 내용(질문, 보기, 정답, 해설)을 수정"""
    global active_quiz, active_quizzes
    quiz_id = data.get("id") or data.get("quiz_id")
    quiz = next((q for q in active_quizzes if q.get("id") == quiz_id), None)
    if not quiz:
        return

    quiz["question"] = data.get("question", quiz.get("question", ""))
    quiz["options"] = data.get("options", quiz.get("options", []))
    quiz["answer"] = data.get("answer", quiz.get("answer", 0))
    quiz["explanation"] = data.get("explanation", quiz.get("explanation", ""))
    if "is_published" in data:
        quiz["is_published"] = data["is_published"]

    save_quiz_to_storage(quiz)

    if quiz.get("is_published"):
        active_quiz = quiz
        emit('quiz_added', quiz, broadcast=True)

    emit('active_quizzes_updated', {
        "active_quizzes": active_quizzes,
        "quiz_stats": get_all_quiz_stats()
    }, broadcast=True)

@socketio.on('delete_quiz')
def handle_delete_quiz(data):
    """교수가 특정 퀴즈 문제를 선택 삭제"""
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
    }, broadcast=True)

@socketio.on('cancel_quiz')
def handle_cancel_quiz(data=None):
    """교수가 출제된 실시간 퀴즈를 취소하고 학생 화면에서 숨김 (차시별 또는 전체)"""
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
    }, broadcast=True)

@socketio.on('submit_quiz_answer')
def handle_submit_quiz_answer(data):
    """학생의 퀴즈 답안 제출 및 문제별 통계 브로드캐스트 & 영구 저장"""
    global quiz_answers_by_id
    quiz_id = data.get("quiz_id")
    if not quiz_id and active_quizzes:
        c = data.get("course")
        s = data.get("session")
        matched = [q for q in active_quizzes if (not c or q.get("course") == c) and (not s or q.get("session") == s)]
        quiz_id = matched[-1]["id"] if matched else active_quizzes[-1]["id"]

    if not quiz_id:
        return

    selected = data.get("selected_option")
    if quiz_id not in quiz_answers_by_id:
        quiz_answers_by_id[quiz_id] = []
    quiz_answers_by_id[quiz_id].append(selected)

    # 영구 저장소의 퀴즈 데이터에도 답안 동기화
    try:
        storage = load_data()
        for c, cdata in storage.get("courses", {}).items():
            for q in cdata.get("quizzes", []):
                if q.get("id") == quiz_id:
                    q.setdefault("answers", []).append(selected)
                    save_data(storage)
                    break
    except Exception as e:
        print(f"답안 영구 저장 오류: {e}")

    stats_info = get_quiz_stats_dict(quiz_id)
    emit('update_quiz_stats', stats_info, broadcast=True)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"[*] 실시간 소통 및 AI 학습 웹앱 서버 가동 시작: http://localhost:{port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
