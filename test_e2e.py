import unittest
import json
import os
import sys
from app import app, socketio, load_data, save_data, init_default_data, DATA_FILE

sys.stdout.reconfigure(encoding='utf-8')

class MultiCourseTeachingAppTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._backup_data = None
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    cls._backup_data = f.read()
            except Exception:
                pass

    @classmethod
    def tearDownClass(cls):
        if cls._backup_data is not None:
            try:
                with open(DATA_FILE, 'w', encoding='utf-8') as f:
                    f.write(cls._backup_data)
            except Exception:
                pass

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

        # 테스트용 데이터 초기화
        save_data(init_default_data())

    def test_1_http_routes_and_pin_auth(self):
        print("\n--- [Test 1] HTTP 라우트 및 교수 PIN 인증 테스트 ---")
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)

        # PIN 인증 실패
        res = self.client.post('/login_professor',
                               data=json.dumps({'pin': '1234'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 401)

        # PIN 인증 성공
        res = self.client.post('/login_professor',
                               data=json.dumps({'pin': '2528'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        print("  ✓ 교수 PIN(2528) 백엔드 이중 검증 통과")

    def test_2_multicourse_and_session_management(self):
        print("\n--- [Test 2] 3개 과목 및 강의시간(세션) 관리 API 테스트 ---")
        with self.client.session_transaction() as sess:
            sess['is_professor'] = True

        # 1. 과목 목록 조회
        res = self.client.get('/api/courses')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        courses = data['courses']
        self.assertIn("원가회계", courses)
        self.assertIn("회계감사", courses)
        self.assertIn("캡스톤디자인(ESG공시)", courses)
        print(f"  ✓ 3개 개설 과목 확인: {courses}")

        # 2. 새로운 차시 추가 (원가회계 -> 4주차)
        res = self.client.post('/api/add_session',
                               data=json.dumps({'course': '원가회계', 'session_name': '4주차'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('4주차', data['sessions'])
        print("  ✓ [원가회계] 새로운 강의시간('4주차') 추가 성공")

        # 3. 활성 세션 변경 (회계감사 - 2주차)
        res = self.client.post('/api/set_active_session',
                               data=json.dumps({'course': '회계감사', 'session': '2주차'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data['active_course'], '회계감사')
        self.assertEqual(data['active_session'], '2주차')
        print("  ✓ 현재 활성 강의시간 [회계감사 - 2주차] 전환 확인")

    def test_3_socketio_course_isolation_and_persistence(self):
        print("\n--- [Test 3] 과목별 피드백 격리 및 영구 누적 저장 테스트 ---")
        student_socket = socketio.test_client(self.app)

        # 1. 원가회계 1주차에 피드백 제출
        student_socket.emit('submit_opinion', {
            'course': '원가회계',
            'session': '1주차',
            'category': '조금 어려움',
            'text': '제조원가와 판관비 분류 기준이 조금 헷갈립니다.'
        })

        # 2. 캡스톤디자인(ESG공시) 1주차에 피드백 제출
        student_socket.emit('submit_opinion', {
            'course': '캡스톤디자인(ESG공시)',
            'session': '1주차',
            'category': '이해 완료',
            'text': 'Scope 1과 2 배출량 산정 차이를 이해했습니다.'
        })

        # 3. 원가회계 2주차에 추가 피드백 제출
        student_socket.emit('submit_opinion', {
            'course': '원가회계',
            'session': '2주차',
            'category': '예제 필요',
            'text': '활동기준원가(ABC) 배부 예시 문제를 더 풀어보고 싶어요.'
        })

        # 과목별 데이터 격리 검증
        res_cost = self.client.get('/api/graph_data?course=원가회계&session=1주차')
        data_cost = json.loads(res_cost.data)
        self.assertEqual(data_cost['total'], 1)
        self.assertEqual(data_cost['recent_opinions'][0]['text'], '제조원가와 판관비 분류 기준이 조금 헷갈립니다.')
        print("  ✓ [원가회계 - 1주차] 피드백 1건 격리 저장 확인")

        res_esg = self.client.get('/api/graph_data?course=캡스톤디자인(ESG공시)&session=1주차')
        data_esg = json.loads(res_esg.data)
        self.assertEqual(data_esg['total'], 1)
        self.assertEqual(data_esg['recent_opinions'][0]['text'], 'Scope 1과 2 배출량 산정 차이를 이해했습니다.')
        print("  ✓ [캡스톤디자인 - 1주차] 피드백 1건 격리 저장 확인")

        res_audit = self.client.get('/api/graph_data?course=회계감사&session=1주차')
        data_audit = json.loads(res_audit.data)
        self.assertEqual(data_audit['total'], 0)
        print("  ✓ [회계감사] 다른 과목 피드백이 유입되지 않는 격리성 검증 완료")

        # 원가회계 전체 누적 데이터 합산 검증
        res_cost_all = self.client.get('/api/graph_data?course=원가회계&session=전체')
        data_cost_all = json.loads(res_cost_all.data)
        self.assertEqual(data_cost_all['total'], 2)
        print("  ✓ [원가회계 - 전체] 1주차 및 2주차 피드백 총 2건 누적 합산 확인")

        student_socket.disconnect()

    def test_4_cumulative_ai_interpretation(self):
        print("\n--- [Test 4] 과목별 누적 데이터 AI 종합 진단 & 해석 API 테스트 ---")
        with self.client.session_transaction() as sess:
            sess['is_professor'] = True

        # 사전 데이터 준비 (원가회계 1주차 & 2주차)
        student_socket = socketio.test_client(self.app)
        student_socket.emit('submit_opinion', {
            'course': '원가회계',
            'session': '1주차',
            'category': '조금 어려움',
            'text': '손익분기점 공식과 안전한계율이 헷갈립니다.'
        })
        student_socket.emit('submit_opinion', {
            'course': '원가회계',
            'session': '2주차',
            'category': '이해 완료',
            'text': 'ABC 활동기준원가 개념은 이해했습니다.'
        })

        # 누적 AI 분석 API 호출
        res = self.client.post('/api/analyze_cumulative',
                               data=json.dumps({'course': '원가회계'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data['course'], '원가회계')
        self.assertIn('analysis_raw', data)
        self.assertTrue(len(data['analysis_raw']) > 50)
        print(f"  ✓ [원가회계] 누적 AI 종합 진단 리포트 생성 성공 (길이: {len(data['analysis_raw'])}자)")

        student_socket.disconnect()

    def test_5_cancel_quiz_flow(self):
        print("\n--- [Test 5] 퀴즈 출제 취소 및 학생 화면 초기화 테스트 ---")
        student_socket = socketio.test_client(self.app)
        prof_socket = socketio.test_client(self.app)

        # 1. 교수 퀴즈 출제
        quiz_data = {
            "course": "원가회계",
            "session": "1주차",
            "question": "테스트 퀴즈 질문입니다.",
            "options": ["보기1", "보기2", "보기3", "보기4"],
            "answer": 0,
            "explanation": "해설입니다."
        }
        prof_socket.emit('send_quiz', quiz_data)

        # 2. 학생이 receive_quiz 수신 확인
        received = student_socket.get_received()
        quiz_events = [e for e in received if e['name'] == 'receive_quiz']
        self.assertTrue(len(quiz_events) > 0, "학생에게 receive_quiz 이벤트가 도달해야 합니다.")
        print("  ✓ 교수 퀴즈 출제 -> 학생 receive_quiz 수신 확인")

        # 3. 교수 퀴즈 취소 신호 전송 (cancel_quiz)
        prof_socket.emit('cancel_quiz')

        # 4. 학생 화면에 clear_quiz 브로드캐스트 이벤트 수신 확인
        received_after_cancel = student_socket.get_received()
        clear_events = [e for e in received_after_cancel if e['name'] == 'clear_quiz']
        self.assertTrue(len(clear_events) > 0, "학생에게 clear_quiz 이벤트가 도달해야 합니다.")
        print("  ✓ 교수 cancel_quiz 전송 -> 학생 clear_quiz 수신 확인")

        student_socket.disconnect()
    def test_6_quiz_course_sync_and_api(self):
        print("\n--- [Test 6] 과목 동기화 및 퀴즈 API 검증 테스트 ---")
        student_socket = socketio.test_client(self.app)

        with self.client.session_transaction() as sess:
            sess['is_professor'] = True

        # 1. 교수가 과목을 '회계감사'로 변경할 때 session_changed 수신 확인
        res = self.client.post('/api/set_active_session',
                               data=json.dumps({'course': '회계감사', 'session': '1주차'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)

        received = student_socket.get_received()
        session_events = [e for e in received if e['name'] == 'session_changed']
        self.assertTrue(len(session_events) > 0, "학생에게 session_changed 이벤트가 도달해야 합니다.")
        self.assertEqual(session_events[0]['args'][0]['active_course'], '회계감사')
        print("  ✓ 교수 활성 과목 전환(회계감사) -> 학생 session_changed 수신 확인")

        # 2. 퀴즈 출제 후 /api/courses 및 /api/current_quiz 검증
        prof_socket = socketio.test_client(self.app)
        quiz_data = {
            "course": "회계감사",
            "session": "1주차",
            "question": "회계감사 감사의견 중 부적정에 해당하는 기준은?",
            "options": ["중요하고 전반적인 왜곡", "제한적인 왜곡", "왜곡 없음", "감사범위 제한"],
            "answer": 0,
            "explanation": "재무제표 왜곡표시가 중요하고 전반적인 경우 부적정의견을 표명합니다."
        }
        prof_socket.emit('send_quiz', quiz_data)

        # /api/courses 확인
        res_courses = self.client.get('/api/courses')
        courses_data = json.loads(res_courses.data)
        self.assertIsNotNone(courses_data.get('active_quiz'))
        self.assertEqual(courses_data['active_quiz']['question'], quiz_data['question'])
        print("  ✓ /api/courses 에 active_quiz 정상 포함 확인")

        # /api/current_quiz 확인
        res_quiz = self.client.get('/api/current_quiz')
        current_quiz_data = json.loads(res_quiz.data)
        self.assertIsNotNone(current_quiz_data.get('active_quiz'))
        self.assertEqual(current_quiz_data['active_quiz']['course'], '회계감사')
        print("  ✓ /api/current_quiz 조회 정상 동작 확인")

        # 취소 후 active_quiz가 None으로 초기화되는지 확인
        prof_socket.emit('cancel_quiz')
        res_quiz_after = self.client.get('/api/current_quiz')
        self.assertIsNone(json.loads(res_quiz_after.data).get('active_quiz'))
        print("  ✓ cancel_quiz 후 active_quiz 초기화 확인")

        student_socket.disconnect()
        prof_socket.disconnect()

    def test_7_professor_course_management(self):
        print("\n--- [Test 7] 교수 과목 추가/수정/삭제 및 권한/실시간 동기화 테스트 ---")
        student_socket = socketio.test_client(self.app)

        # 1. 비인가(학생) 상태에서 과목 추가/수정/삭제 시도 -> 401 차단
        res = self.client.post('/api/add_course',
                               data=json.dumps({'course_name': '임의과목'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 401)

        res = self.client.post('/api/rename_course',
                               data=json.dumps({'old_name': '원가회계', 'new_name': '관리회계'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 401)

        res = self.client.post('/api/delete_course',
                               data=json.dumps({'course': '원가회계'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 401)
        print("  ✓ 비인가 접근 401 차단 확인 (add/rename/delete)")

        # 2. 교수 세션 활성화
        with self.client.session_transaction() as sess:
            sess['is_professor'] = True

        # 3. 과목 추가 유효성 검사 및 신규 과목 '세무회계' 추가
        res = self.client.post('/api/add_course',
                               data=json.dumps({'course_name': ''}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)

        res = self.client.post('/api/add_course',
                               data=json.dumps({'course_name': '원가회계'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)

        res = self.client.post('/api/add_course',
                               data=json.dumps({'course_name': '세무회계'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIn('세무회계', data['courses'])
        print("  ✓ [세무회계] 신규 과목 추가 성공")

        # 학생 소켓이 courses_updated 이벤트를 수신했는지 확인
        received = student_socket.get_received()
        course_events = [e for e in received if e['name'] == 'courses_updated']
        self.assertTrue(len(course_events) > 0, "학생에게 courses_updated 이벤트가 브로드캐스트되어야 합니다.")
        self.assertIn('세무회계', course_events[-1]['args'][0]['courses'])
        print("  ✓ 신규 과목 추가 -> 학생 courses_updated 실시간 이벤트 수신 확인")

        # 4. 과목명 수정 ('세무회계' -> '고급세무회계')
        res = self.client.post('/api/rename_course',
                               data=json.dumps({'old_name': '존재하지않음', 'new_name': '새과목'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 404)

        res = self.client.post('/api/rename_course',
                               data=json.dumps({'old_name': '세무회계', 'new_name': '원가회계'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)

        res = self.client.post('/api/rename_course',
                               data=json.dumps({'old_name': '세무회계', 'new_name': '고급세무회계'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertNotIn('세무회계', data['courses'])
        self.assertIn('고급세무회계', data['courses'])
        print("  ✓ [세무회계 -> 고급세무회계] 과목명 수정 성공")

        # 5. 기존 피드백 데이터 승계 및 활성 과목 변경 검증
        # 원가회계 1주차에 피드백 추가
        student_socket.emit('submit_opinion', {
            'course': '원가회계',
            'session': '1주차',
            'category': '이해 완료',
            'text': '원가 배부 개념 테스트'
        })
        # 활성 과목으로 설정되어 있는 원가회계를 '관리회계'로 수정
        res = self.client.post('/api/rename_course',
                               data=json.dumps({'old_name': '원가회계', 'new_name': '관리회계'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)

        # 데이터 파일 직접 검증: '관리회계'에 기존 의견이 승계되었는지 및 이전 이름이 부활하지 않는지
        stored = load_data()
        self.assertIn('관리회계', stored['courses'])
        self.assertNotIn('원가회계', stored['courses'])
        self.assertEqual(stored['active_course'], '관리회계')
        self.assertEqual(len(stored['courses']['관리회계']['opinions']), 1)
        self.assertEqual(stored['courses']['관리회계']['opinions'][0]['course'], '관리회계')
        print("  ✓ 과목명 수정 시 기존 의견 데이터 및 활성 과목 정상 승계/연동 확인")

        # 6. 과목 삭제 기능 검증
        res = self.client.post('/api/delete_course',
                               data=json.dumps({'course': '고급세무회계'}),
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertNotIn('고급세무회계', data['courses'])
        print("  ✓ [고급세무회계] 과목 삭제 성공")

        student_socket.disconnect()

    def test_8_quiz_course_and_session_isolation(self):
        print("\n--- [Test 8] 퀴즈 특정 과목 및 차시(세션) 격리 페이로드 검증 ---")
        prof_socket = socketio.test_client(self.app)
        student_socket = socketio.test_client(self.app)

        # 1. 원가회계 1차시에 퀴즈 출제
        quiz_cost_1 = {
            "course": "원가회계",
            "session": "1주차",
            "question": "원가의 추적가능성에 따른 분류는?",
            "options": ["직접원가와 간접원가", "제조원가와 판관비", "변동원가와 고정원가", "기회원가와 매몰원가"],
            "answer": 0,
            "explanation": "추적가능성에 따라 특정 원가대상에 직접 추적할 수 있는 직접원가와 추적할 수 없는 간접원가로 구분합니다."
        }
        prof_socket.emit('send_quiz', quiz_cost_1)

        # 학생 소켓이 받은 퀴즈 데이터에 course와 session이 정확히 명시되어 있는지 확인
        received = student_socket.get_received()
        quiz_events = [e for e in received if e['name'] in ('send_quiz', 'receive_quiz')]
        self.assertTrue(len(quiz_events) > 0, "학생에게 퀴즈 브로드캐스트 이벤트가 전달되어야 합니다.")
        received_quiz = quiz_events[0]['args'][0]
        self.assertEqual(received_quiz['course'], '원가회계')
        self.assertEqual(received_quiz['session'], '1주차')
        print("  ✓ 원가회계 1주차 퀴즈 브로드캐스트 페이로드 확인: 과목='원가회계', 세션='1주차'")

        # 2. /api/current_quiz 확인
        res = self.client.get('/api/current_quiz')
        curr_quiz = json.loads(res.data).get('active_quiz')
        self.assertIsNotNone(curr_quiz)
        self.assertEqual(curr_quiz['course'], '원가회계')
        self.assertEqual(curr_quiz['session'], '1주차')
        print("  ✓ /api/current_quiz 응답 내 course/session 격리 식별자 검증 통과")

        # 퀴즈 정리
        prof_socket.emit('cancel_quiz')
        prof_socket.disconnect()
        student_socket.disconnect()

    def test_9_multi_quiz_per_session_and_stats(self):
        print("\n--- [Test 9] 동일 차시 내 다중 퀴즈 출제 및 문제별 개별 통계 검증 ---")
        prof_socket = socketio.test_client(self.app)
        student_socket = socketio.test_client(self.app)

        # 1. 원가회계 1주차에 문제 1 출제
        quiz1 = {
            "id": "quiz_test_1",
            "course": "원가회계",
            "session": "1주차",
            "question": "문제 1: 고정원가와 변동원가의 합은?",
            "options": ["총원가", "제조원가", "매출원가", "기회원가"],
            "answer": 0,
            "explanation": "총원가는 고정원가와 변동원가의 합계입니다."
        }
        prof_socket.emit('send_quiz', quiz1)

        # 2. 동일한 원가회계 1주차에 문제 2 추가 출제
        quiz2 = {
            "id": "quiz_test_2",
            "course": "원가회계",
            "session": "1주차",
            "question": "문제 2: 공헌이익률 공식은?",
            "options": ["공헌이익 / 매출액", "매출액 / 고정비", "영업이익 / 공헌이익", "변동비 / 공헌이익"],
            "answer": 0,
            "explanation": "공헌이익률은 공헌이익을 매출액으로 나눈 비율입니다."
        }
        prof_socket.emit('send_quiz', quiz2)

        # 3. API 확인: active_quizzes에 2개 문제가 모두 등록되어 있는지 확인
        res = self.client.get('/api/current_quiz')
        data = json.loads(res.data)
        quizzes = data.get('active_quizzes', [])
        self.assertEqual(len(quizzes), 2, "동일 차시에 2개의 문제가 등록되어야 합니다.")
        self.assertEqual(quizzes[0]['id'], 'quiz_test_1')
        self.assertEqual(quizzes[1]['id'], 'quiz_test_2')
        print(f"  ✓ 동일 차시 다중 문제 2건 등록 확인 (ID: {quizzes[0]['id']}, {quizzes[1]['id']})")

        # 4. 학생 소켓에서 문제 1에 대한 답안 제출
        student_socket.emit('submit_quiz_answer', {
            'quiz_id': 'quiz_test_1',
            'selected_option': 0
        })

        # 통계 브로드캐스트 수신 확인 (문제 1에 대한 통계만 갱신)
        received = prof_socket.get_received()
        stats_events = [e for e in received if e['name'] == 'update_quiz_stats']
        self.assertTrue(len(stats_events) > 0)
        q1_stat = stats_events[-1]['args'][0]
        self.assertEqual(q1_stat['quiz_id'], 'quiz_test_1')
        self.assertEqual(q1_stat['total_responses'], 1)
        self.assertEqual(q1_stat['stats']['0'], 1)
        print("  ✓ 문제 1 답안 제출 -> 문제 1 개별 통계(총 1명, 보기 1: 1명) 실시간 집계 확인")

        # 5. 학생 소켓에서 문제 2에 대한 답안 제출
        student_socket.emit('submit_quiz_answer', {
            'quiz_id': 'quiz_test_2',
            'selected_option': 1
        })
        received2 = prof_socket.get_received()
        stats2_events = [e for e in received2 if e['name'] == 'update_quiz_stats']
        self.assertTrue(len(stats2_events) > 0)
        q2_stat = stats2_events[-1]['args'][0]
        self.assertEqual(q2_stat['quiz_id'], 'quiz_test_2')
        self.assertEqual(q2_stat['total_responses'], 1)
        self.assertEqual(q2_stat['stats']['1'], 1)
        print("  ✓ 문제 2 답안 제출 -> 문제 2 개별 통계(총 1명, 보기 2: 1명) 실시간 분리 집계 확인")

        # 6. 개별 문제 삭제 (문제 1 삭제)
        prof_socket.emit('delete_quiz', {'quiz_id': 'quiz_test_1'})
        res_del = self.client.get('/api/current_quiz')
        data_del = json.loads(res_del.data)
        quizzes_del = data_del.get('active_quizzes', [])
        self.assertEqual(len(quizzes_del), 1)
        self.assertEqual(quizzes_del[0]['id'], 'quiz_test_2')
        print("  ✓ 개별 문제(문제 1) 삭제 -> 문제 2는 온전히 유지됨 확인")

        # 7. 전체 퀴즈 취소
        prof_socket.emit('cancel_quiz')
        res_cancel = self.client.get('/api/current_quiz')
        data_cancel = json.loads(res_cancel.data)
        self.assertEqual(len(data_cancel.get('active_quizzes', [])), 0)
        print("  ✓ 전체 퀴즈 취소 정상 확인")

        prof_socket.disconnect()
        student_socket.disconnect()

    def test_10_quiz_draft_and_stepwise_publishing(self):
        print("\n--- [Test 10] 문제 임시 저장 및 단계별 학생 공개 기능 검증 ---")
        prof_socket = socketio.test_client(self.app)
        student_socket = socketio.test_client(self.app)

        # 1. 교수가 문제 2건(A, B)을 임시 저장 (save_draft_quiz)
        draft_a = {
            "id": "draft_quiz_A",
            "course": "원가회계",
            "session": "1주차",
            "question": "임시 문제 A: 변동원가의 특징은?",
            "options": ["조업도에 비례", "조업도와 무관", "항상 일정", "0이다"],
            "answer": 0,
            "explanation": "변동원가는 조업도에 비례하여 발생합니다."
        }
        draft_b = {
            "id": "draft_quiz_B",
            "course": "원가회계",
            "session": "1주차",
            "question": "임시 문제 B: 고정원가의 특징은?",
            "options": ["조업도와 무관하게 일정", "조업도에 비례", "단위당 일정", "알수없음"],
            "answer": 0,
            "explanation": "고정원가는 관련범위 내에서 총액이 일정합니다."
        }
        prof_socket.emit('save_draft_quiz', draft_a)
        prof_socket.emit('save_draft_quiz', draft_b)

        # 학생 소켓이 receive_quiz 또는 send_quiz 이벤트를 받지 않았는지 검증
        student_received = student_socket.get_received()
        quiz_events = [e for e in student_received if e['name'] in ('send_quiz', 'receive_quiz', 'quiz_added')]
        self.assertEqual(len(quiz_events), 0, "임시 저장된 문제는 학생에게 공개 이벤트가 발생하지 않아야 합니다.")

        # 학생 시점에서 /api/current_quiz 조회 시 0건이어야 함
        res_student = self.client.get('/api/current_quiz')
        data_student = json.loads(res_student.data)
        self.assertEqual(len(data_student.get('active_quizzes', [])), 0, "학생에게는 임시 저장된 퀴즈가 노출되지 않아야 합니다.")
        print("  ✓ 문제 2건 임시 저장 -> 학생에게 미공개 및 격리 검증 완료")

        # 교수 세션으로 /api/current_quiz 조회 시 2건 모두 조회되어야 함
        with self.client.session_transaction() as sess:
            sess['is_professor'] = True
        res_prof = self.client.get('/api/current_quiz')
        data_prof = json.loads(res_prof.data)
        self.assertEqual(len(data_prof.get('active_quizzes', [])), 2, "교수에게는 임시 저장된 퀴즈 2건이 모두 보여야 합니다.")
        print("  ✓ 교수 권한 조회 -> 임시 저장 퀴즈 2건 정상 보관 확인")

        # 2. 문제 A만 학생에게 공개 (publish_quiz)
        prof_socket.emit('publish_quiz', {'quiz_id': 'draft_quiz_A'})

        # 학생 소켓이 quiz_published 또는 quiz_added 이벤트 수신 확인
        student_received_after_pub = student_socket.get_received()
        pub_events = [e for e in student_received_after_pub if e['name'] in ('quiz_published', 'quiz_added')]
        self.assertTrue(len(pub_events) > 0, "학생에게 공개 이벤트가 전파되어야 합니다.")
        self.assertEqual(pub_events[0]['args'][0]['id'], 'draft_quiz_A')

        # 학생 시점에서 /api/current_quiz 조회 시 문제 A만 1건 노출
        with self.client.session_transaction() as sess:
            sess['is_professor'] = False
        res_student2 = self.client.get('/api/current_quiz')
        data_student2 = json.loads(res_student2.data)
        quizzes_student2 = data_student2.get('active_quizzes', [])
        self.assertEqual(len(quizzes_student2), 1)
        self.assertEqual(quizzes_student2[0]['id'], 'draft_quiz_A')
        print("  ✓ 문제 A 개별 공개 -> 학생 화면에 문제 A만 1건 실시간 출제 확인")

        # 3. 문제 B도 공개 (publish_quiz)
        prof_socket.emit('publish_quiz', {'quiz_id': 'draft_quiz_B'})
        res_student3 = self.client.get('/api/current_quiz')
        data_student3 = json.loads(res_student3.data)
        self.assertEqual(len(data_student3.get('active_quizzes', [])), 2)
        print("  ✓ 문제 B 추가 공개 -> 학생 화면에 문제 A, B 총 2건 모두 출제 확인")

        # 4. 문제 B 비공개 전환 (unpublish_quiz)
        prof_socket.emit('unpublish_quiz', {'quiz_id': 'draft_quiz_B'})
        res_student4 = self.client.get('/api/current_quiz')
        data_student4 = json.loads(res_student4.data)
        quizzes_student4 = data_student4.get('active_quizzes', [])
        self.assertEqual(len(quizzes_student4), 1)
        self.assertEqual(quizzes_student4[0]['id'], 'draft_quiz_A')
        print("  ✓ 문제 B 비공개 전환 -> 학생 화면에서 문제 B가 즉시 내려가고 문제 A만 유지됨 확인")

        # 퀴즈 전체 정리
        prof_socket.emit('cancel_quiz')
        prof_socket.disconnect()
        student_socket.disconnect()

    def test_11_material_upload_and_comprehensive_ai_analysis(self):
        print("\n--- [Test 11] 주차별 수업자료(PDF/PPT) 업로드 및 AI 종합 분석 보고서 검증 ---")
        import io

        with self.client.session_transaction() as sess:
            sess['is_professor'] = True

        # 1. 수업자료 업로드 (원가회계 1주차 교안)
        sample_content = "제1장 원가회계의 기초 및 원가의 개념과 분류\n총원가는 재료원가, 노무원가, 제조경비로 구성된다.\n추적가능성에 따른 직접원가와 간접원가, 원가행태에 따른 고정원가와 변동원가 분류 원리.".encode('utf-8')
        data = {
            'course': '원가회계',
            'session': '1주차',
            'file': (io.BytesIO(sample_content), '원가회계_1주차_교안.txt')
        }
        res_upload = self.client.post('/api/upload_material', data=data, content_type='multipart/form-data')
        self.assertEqual(res_upload.status_code, 200)
        data_up = json.loads(res_upload.data)
        self.assertTrue(data_up.get('success'))
        self.assertEqual(data_up['material']['filename'], '원가회계_1주차_교안.txt')
        print("  ✓ 수업자료(교안) 업로드 및 텍스트 자동 파싱 저장 확인")

        # 2. 수업자료 정보 조회
        res_info = self.client.get('/api/material_info?course=원가회계&session=1주차')
        self.assertEqual(res_info.status_code, 200)
        data_info = json.loads(res_info.data)
        self.assertTrue(data_info.get('has_material'))
        self.assertEqual(data_info.get('filename'), '원가회계_1주차_교안.txt')
        print("  ✓ 수업자료 상태 조회 API (/api/material_info) 연동 확인")

        # 3. 퀴즈 데이터 및 학생 피드백 준비
        prof_socket = socketio.test_client(self.app)
        student_socket = socketio.test_client(self.app)

        prof_socket.emit('send_quiz', {
            'course': '원가회계',
            'session': '1주차',
            'question': '총원가의 3요소로 옳은 것은?',
            'options': ['재료원가, 노무원가, 경비', '고정비, 변동비, 준변동비', '직접비, 간접비, 기회원가', '관련원가, 매몰원가, 비제조원가'],
            'answer': 0,
            'explanation': '총원가는 재료원가, 노무원가, 제조경비의 합으로 구성됩니다.'
        })

        student_socket.emit('submit_opinion', {
            'course': '원가회계',
            'session': '1주차',
            'category': '조금 어려움',
            'text': '제조간접원가 배부 공식이 헷갈립니다.'
        })

        # 4. 종합 AI 분석 보고서 생성 (/api/analyze_opinions)
        res_analysis = self.client.post('/api/analyze_opinions', json={'course': '원가회계', 'session': '1주차'})
        self.assertEqual(res_analysis.status_code, 200)
        data_analysis = json.loads(res_analysis.data)
        raw_report = data_analysis.get('analysis_raw', '')

        self.assertIn("학생들을 위한 맞춤형 학습 제안", raw_report)
        self.assertIn("교수자를 위한 다음 강의 개선 제안", raw_report)
        print("  ✓ 수업자료 + 퀴즈 채점결과 + 학생 피드백 3중 결합 AI 종합 분석 보고서 검증 완료")

        # 5. 자료 삭제
        res_del = self.client.post('/api/delete_material', json={'course': '원가회계', 'session': '1주차'})
        self.assertEqual(res_del.status_code, 200)
        res_info_after = self.client.get('/api/material_info?course=원가회계&session=1주차')
        self.assertFalse(json.loads(res_info_after.data).get('has_material'))
        print("  ✓ 수업자료 삭제 API 연동 확인")

        prof_socket.emit('cancel_quiz')
        prof_socket.disconnect()
        student_socket.disconnect()

    def test_12_student_self_study_ai_report(self):
        print("\n--- [Test 12] 학생 자가학습 맞춤형 AI 분석보고서 발행 및 실시간 배포 검증 ---")
        prof_socket = socketio.test_client(self.app)
        student_socket = socketio.test_client(self.app)

        with self.client.session_transaction() as sess:
            sess['is_professor'] = True

        # 1. 퀴즈 1건 및 학생 피드백 제출
        prof_socket.emit('send_quiz', {
            'course': '원가회계',
            'session': '1주차',
            'question': '원가의 추적가능성에 따른 분류는?',
            'options': ['직접원가와 간접원가', '제조원가와 비제조원가', '변동원가와 고정원가', '기회원가와 매몰원가'],
            'answer': 0,
            'explanation': '추적가능성에 따라 직접원가와 간접원가로 분류합니다.'
        })
        student_socket.emit('submit_opinion', {
            'course': '원가회계',
            'session': '1주차',
            'category': '조금 어려움',
            'text': '간접원가 추적 구분이 헷갈립니다.'
        })

        # 2. 교수 종합 분석 보고서 생성 실행 (/api/analyze_opinions)
        res_analysis = self.client.post('/api/analyze_opinions', json={'course': '원가회계', 'session': '1주차'})
        self.assertEqual(res_analysis.status_code, 200)
        data = json.loads(res_analysis.data)

        # 교수용 보고서와 학생용 보고서가 모두 도출되었는지 확인
        self.assertTrue(bool(data.get('analysis_raw')), "교수용 분석 보고서가 존재해야 합니다.")
        self.assertTrue(bool(data.get('student_report')), "학생 자가학습용 분석 보고서가 존재해야 합니다.")
        student_report = data['student_report']
        self.assertIn("자가학습을 위한 맞춤형 AI 분석보고서", student_report)
        print("  ✓ 교수 종합 분석 시 학생 자가학습 보고서 동시 생성 확인")

        # 3. 학생 소켓 실시간 브로드캐스트 수신 확인
        received = student_socket.get_received()
        report_events = [e for e in received if e['name'] == 'student_report_updated']
        self.assertTrue(len(report_events) > 0, "학생 소켓에 student_report_updated 이벤트가 전달되어야 합니다.")
        event_payload = report_events[-1]['args'][0]
        self.assertEqual(event_payload['course'], '원가회계')
        self.assertEqual(event_payload['session'], '1주차')
        self.assertIn("자가학습을 위한 맞춤형 AI 분석보고서", event_payload['student_report'])
        print("  ✓ 학생 소켓 student_report_updated 실시간 브로드캐스트 수신 확인")

        # 4. 학생 조회 API 검증 (/api/student_report)
        # 1주차(발행된 주차) 조회 -> has_report: True
        res_rep = self.client.get('/api/student_report?course=원가회계&session=1주차')
        self.assertEqual(res_rep.status_code, 200)
        rep_json = json.loads(res_rep.data)
        self.assertTrue(rep_json.get('has_report'))
        self.assertEqual(rep_json.get('course'), '원가회계')
        self.assertEqual(rep_json.get('session'), '1주차')
        self.assertIn("자가학습을 위한 맞춤형 AI 분석보고서", rep_json.get('student_report'))
        print("  ✓ 학생 전용 보고서 조회 API (/api/student_report) 정상 응답 확인")

        # 3주차(미발행 주차) 조회 -> has_report: False
        res_empty = self.client.get('/api/student_report?course=원가회계&session=3주차')
        self.assertEqual(res_empty.status_code, 200)
        self.assertFalse(json.loads(res_empty.data).get('has_report'))
        print("  ✓ 미발행 주차에 대한 has_report: False 정상 응답 확인")

        prof_socket.emit('cancel_quiz')
        prof_socket.disconnect()
        student_socket.disconnect()

    def test_13_session_switching_report_and_draft_isolation(self):
        print("\n--- [Test 13] 주차 변경 시 AI 분석보고서 격리 및 2주차 임시저장 퀴즈 복원 검증 ---")
        with self.client.session_transaction() as sess:
            sess['is_professor'] = True

        prof_socket = socketio.test_client(self.app)
        student_socket = socketio.test_client(self.app)

        # 1. 원가회계 2주차 임시 저장 퀴즈 등록
        w2_draft = {
            "id": "quiz_cost_w2_draft_1",
            "course": "원가회계",
            "session": "2주차",
            "question": "Q1 다음 중 의사결정에 영향을 미치는 원가가 아닌 것은?",
            "options": ["관련원가", "기발생원가", "기회원가", "관련원가와 기회원가 모두"],
            "answer": 1,
            "explanation": "기발생원가(매몰원가)는 과거의 의사결정으로 이미 발생한 원가로서 의사결정에 영향을 미치지 않는 비관련원가입니다.",
            "is_published": False
        }
        prof_socket.emit('save_draft_quiz', w2_draft)

        # 2. 교수 권한으로 /api/current_quiz 조회 -> 2주차 임시저장 퀴즈 정상 확인
        res_prof = self.client.get('/api/current_quiz')
        self.assertEqual(res_prof.status_code, 200)
        prof_quizzes = json.loads(res_prof.data).get('active_quizzes', [])
        w2_found = next((q for q in prof_quizzes if q.get('id') == 'quiz_cost_w2_draft_1'), None)
        self.assertIsNotNone(w2_found, "교수 권한에서 2주차 임시 저장 퀴즈가 조회되어야 합니다.")
        self.assertEqual(w2_found['session'], '2주차')
        self.assertFalse(w2_found['is_published'])
        self.assertEqual(w2_found['answer'], 1)
        print("  ✓ 원가회계 2주차 임시저장 퀴즈 보관 및 교수 조회 정상 확인")

        # 3. 학생(비인가) 권한으로 /api/current_quiz 조회 -> 임시저장 퀴즈는 학생에게 미노출
        with self.client.session_transaction() as sess:
            sess['is_professor'] = False

        res_stud = self.client.get('/api/current_quiz')
        self.assertEqual(res_stud.status_code, 200)
        stud_quizzes = json.loads(res_stud.data).get('active_quizzes', [])
        w2_in_student = next((q for q in stud_quizzes if q.get('id') == 'quiz_cost_w2_draft_1'), None)
        self.assertIsNone(w2_in_student, "학생에게는 2주차 임시저장 퀴즈가 노출되지 않아야 합니다.")
        print("  ✓ 2주차 임시저장 퀴즈의 학생 대상 철저한 비노출 격리 확인")

        # 4. 세션 변경 시 AI 분석보고서 격리 검증 (/api/session_report, /api/professor_report)
        with self.client.session_transaction() as sess:
            sess['is_professor'] = True

        # 1주차 분석보고서 생성
        self.client.post('/api/analyze_opinions', json={'course': '원가회계', 'session': '1주차'})

        # 1주차 보고서 조회 -> has_report: True
        res_rep_w1 = self.client.get('/api/session_report?course=원가회계&session=1주차')
        self.assertEqual(res_rep_w1.status_code, 200)
        rep_w1 = json.loads(res_rep_w1.data)
        self.assertTrue(rep_w1.get('has_report'))
        self.assertEqual(rep_w1.get('session'), '1주차')
        self.assertTrue(bool(rep_w1.get('professor_report')))
        print("  ✓ 1주차 AI 분석보고서 저장 및 조회 확인")

        # 2주차 보고서 조회 -> has_report: False (1주차 보고서가 2주차로 유출되지 않음)
        res_rep_w2 = self.client.get('/api/session_report?course=원가회계&session=2주차')
        self.assertEqual(res_rep_w2.status_code, 200)
        rep_w2 = json.loads(res_rep_w2.data)
        self.assertFalse(rep_w2.get('has_report'))
        self.assertEqual(rep_w2.get('professor_report'), "")
        print("  ✓ 2주차로 주차 변경 시 1주차 AI 보고서 잔존 차단 (격리 완료)")

        # 5. 2주차 퀴즈 공개 전환 검증
        prof_socket.emit('publish_quiz', {'quiz_id': 'quiz_cost_w2_draft_1'})
        with self.client.session_transaction() as sess:
            sess['is_professor'] = False
        res_stud_pub = self.client.get('/api/current_quiz')
        stud_quizzes_pub = json.loads(res_stud_pub.data).get('active_quizzes', [])
        w2_pub = next((q for q in stud_quizzes_pub if q.get('id') == 'quiz_cost_w2_draft_1'), None)
        self.assertIsNotNone(w2_pub, "공개 전환 후 학생 화면에서도 2주차 퀴즈가 노출되어야 합니다.")
        print("  ✓ 2주차 퀴즈 학생 공개 전환 및 조회 연동 검증 완료")

        prof_socket.emit('cancel_quiz')
        prof_socket.disconnect()
        student_socket.disconnect()

if __name__ == '__main__':
    unittest.main()


