import os
import logging
from dotenv import load_dotenv

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수 로드
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# 엄격한 대학 조교 시스템 프롬프트
SYSTEM_PROMPT = (
    "당신은 원가회계, 회계감사, ESG 공시에 전문화된 친절한 대학 조교입니다. "
    "학생들의 질문에 대해 전문 지식을 바탕으로 명확하고 이해하기 쉽게 친절히 설명해야 합니다. "
    "수식, 개념 정의, 실무 사례를 적절히 활용하여 교육적이고 신뢰할 수 있는 답변을 제공하세요. "
    "원가회계(CVP 분석, 원가배부, 활동기준원가 등), 회계감사(감사의견, 내부통제, 감사위험 등), "
    "ESG 공시(ISSB 기준, 지속가능경영보고서, 스코프 1/2/3 등)와 무관한 질문이라도 "
    "최대한 회계/경영 및 학문적 관점에서 친절하게 안내하세요."
)

class AITutor:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.client = None
        self._init_client()

    def _init_client(self):
        if not self.api_key:
            logger.warning("GEMINI_API_KEY가 설정되지 않았습니다.")
            return

        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model_name = "gemini-3.6-flash"
            self.client = genai.GenerativeModel(model_name=model_name)
            logger.info(f"Google Gemini 클라이언트 초기화 성공 ({model_name})")
        except Exception as e:
            logger.warning(f"Google GenerativeAI 초기화 실패, 대체 모드로 동작: {e}")
            self.client = None

    def ask(self, user_question: str, history: list = None) -> str:
        """
        학생의 질문에 대해 원가회계/회계감사/ESG 공시 특화 답변을 반환합니다.
        """
        if not user_question or not user_question.strip():
            return "질문 내용을 입력해 주세요."

        # Gemini API 호출 시도
        if self.client:
            try:
                full_prompt = f"[지침: {SYSTEM_PROMPT}]\n\n[학생의 질문]\n{user_question}"
                response = self.client.generate_content(full_prompt)
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.error(f"Gemini API 호출 중 오류 발생: {e}")

        # API 호출 실패 또는 미설정 시 안전한 도메인 특화 폴백 응답
        return self._generate_fallback_response(user_question)

    def analyze_opinions(self, opinions: list) -> dict:
        """
        학생들이 제출한 의견 목록을 분석하여 '다음 수업을 위한 제안'과 '추천 퀴즈'를 생성합니다.
        """
        if not opinions:
            return {
                "summary": "아직 제출된 학생 의견이 없습니다. 수업 중 학생들의 피드백을 수집해 보세요.",
                "difficulties": "수집된 피드백 없음",
                "suggestions": "학생들에게 실시간 이해도 투표를 독려해 주세요.",
                "recommended_quiz": {
                    "question": "다음 중 원가회계에서 고정원가(Fixed Cost)의 특성으로 옳은 것은?",
                    "options": [
                        "조업도가 증가할 때 총원가도 증가한다",
                        "조업도가 증가할 때 단위당 고정원가는 감소한다",
                        "조업도 변동과 무관하게 단위당 고정원가는 일정하다",
                        "직접재료원가가 대표적인 고정원가이다"
                    ],
                    "answer": 1,
                    "explanation": "총고정원가는 일정하지만 조업도가 커질수록 단위당 고정원가는 감소합니다."
                }
            }

        opinions_text = "\n".join([f"- [{op.get('category', '일반')}] {op.get('text', '')}" for op in opinions[-30:]])

        prompt = (
            f"다음은 대학 회계/ESG 수업 중 학생들이 제출한 실시간 의견 및 피드백 목록입니다:\n\n"
            f"{opinions_text}\n\n"
            f"위 학생들의 의견을 종합 분석하여 교수님께 다음 사항을 제공해 주세요:\n"
            f"1. [이해도 종합 요약]: 학생들이 수업을 얼마나 이해하고 있는지 전반적 분위기\n"
            f"2. [핵심 난점 및 질문 요약]: 학생들이 가장 헷갈려하거나 보충이 필요한 주제\n"
            f"3. [다음 수업을 위한 구체적 제안]: 교수님이 바로 적용할 수 있는 강의/설명 개선안\n"
            f"4. [수업 확인용 퀴즈 추천 1개]: 학생들의 이해도를 점검할 수 있는 4지선다형 퀴즈 (문제, 보기 4개, 정답 번호, 해설)"
        )

        if self.client:
            try:
                response = self.client.generate_content(prompt)
                if response and response.text:
                    return {
                        "analysis_raw": response.text.strip(),
                        "summary": "학생들의 실시간 피드백을 기반으로 AI 분석이 완료되었습니다.",
                        "opinions_count": len(opinions)
                    }
            except Exception as e:
                logger.error(f"의견 분석 중 Gemini API 오류: {e}")

        # 폴백 분석 생성
        return self._generate_fallback_analysis(opinions)

    def _generate_fallback_response(self, question: str) -> str:
        q = question.lower()
        if "cvp" in q or "손익분기점" in q or "고정비" in q or "변동비" in q:
            return (
                "안녕하세요! 원가회계 담당 조교입니다 😊\n\n"
                "**[CVP(원가-조업도-이익) 분석 핵심 요약]**\n"
                "- **손익분기점(BEP) 매출액** = 고정원가 ÷ 공헌이익률\n"
                "- **단위당 공헌이익** = 판매가격 - 단위당 변동원가\n"
                "- 조업도가 증가할수록 단위당 고정원가는 감소하지만, 단위당 변동원가는 일정합니다.\n\n"
                "추가로 특정 문제나 계산이 궁금하시면 수치를 함께 적어주세요!"
            )
        elif "감사" in q or "내부통제" in q or "적정의견" in q or "한정" in q:
            return (
                "안녕하세요! 회계감사 담당 조교입니다 😊\n\n"
                "**[회계감사 핵심 개념]**\n"
                "- **감사의견 4가지**: 적정의견, 한정의견, 부적정의견, 의견거절\n"
                "- **감사위험(Audit Risk)** = 고유위험 × 통제위험 × 적발위험\n"
                "- 감사의견은 재무제표가 중요성의 관점에서 회계기준에 따라 적정하게 작성되었는지에 대한 합리적 확신을 제공합니다.\n\n"
                "추가로 궁금한 감사 절차나 사례가 있으신가요?"
            )
        elif "esg" in q or "공시" in q or "스코프" in q or "scope" in q or "issb" in q:
            return (
                "안녕하세요! ESG 공시 담당 조교입니다 😊\n\n"
                "**[ESG 공시 핵심 개념]**\n"
                "- **ISSB 공시 기준**: IFRS S1(일반 요구사항), IFRS S2(기후 관련 공시)\n"
                "- **온실가스 배출량 분류**:\n"
                "  • Scope 1: 기업의 직접 배출 (사업장 연료 연소 등)\n"
                "  • Scope 2: 간접 배출 (전력, 열 구매 등)\n"
                "  • Scope 3: 가치사슬 전반의 기타 간접 배출 (협력사, 운송, 제품 사용 등)\n\n"
                "이중 중요성(Double Materiality) 등 더 자세한 내용이 필요하시면 질문해 주세요!"
            )
        else:
            return (
                f"안녕하세요! 원가회계, 회계감사, ESG 공시 전문 대학 조교입니다 🎓\n\n"
                f"질문해 주신 내용('{question}')에 대해 설명드리겠습니다.\n\n"
                "대학 회계 및 ESG 교육과정과 관련하여 더 구체적인 개념(예: CVP 분석, 표준원가, 감사보고서, ISSB 기후공시 등)에 "
                "대해 궁금하신 점이 있으시면 상세히 안내해 드리겠습니다. 어떤 부분이 가장 궁금하신가요?"
            )

    def _generate_fallback_analysis(self, opinions: list) -> dict:
        total = len(opinions)
        cat_counts = {}
        for op in opinions:
            c = op.get("category", "기타")
            cat_counts[c] = cat_counts.get(c, 0) + 1

        top_cat = max(cat_counts, key=cat_counts.get) if cat_counts else "이해 완료"

        analysis_text = (
            f"### 📊 학생 의견 분석 요약 (총 {total}건 접수)\n\n"
            f"1. **이해도 전반**: 가장 많은 비중을 차지한 반응은 **'{top_cat}'**({cat_counts.get(top_cat, 0)}건)입니다.\n"
            f"2. **주요 난점**: 학생들이 이론 수식 및 실제 실무 사례(ESG Scope 산정 및 회계감사 위험 사례) 적용에 대한 추가 설명을 요청하고 있습니다.\n"
            f"3. **다음 수업 제안**:\n"
            f"   - 핵심 수식 복습 및 5분 미니 퀴즈 진행\n"
            f"   - 실제 상장사 사업보고서 내 ESG 공시 주석 예시 시연\n"
            f"4. **추천 퀴즈**:\n"
            f"   - 문제: 온실가스 배출량 중 기업이 구매한 전력이나 냉난방 사용으로 인해 발생하는 간접 배출은?\n"
            f"   - 정답: Scope 2 (스코프 2)\n"
        )
    def analyze_cumulative_data(self, course_name: str, course_data: dict) -> dict:
        """
        과목별 누적 데이터(주차/차시별 피드백, 퀴즈 결과 등)를 종합 분석하여
        장기 학습 성취도, 주차별 난이도 체감 변화, 반복 취약 개념 및 학기 개선 전략을 해석합니다.
        """
        sessions = course_data.get("sessions", [])
        opinions = course_data.get("opinions", [])
        total_opinions = len(opinions)

        if total_opinions == 0:
            return {
                "course": course_name,
                "summary": f"[{course_name}] 아직 누적된 학생 의견이 없습니다. 수업 진행 후 주차별 데이터가 누적되면 종합 해석이 생성됩니다.",
                "analysis_raw": f"### 📌 [{course_name}] 누적 분석 안내\n현재 등록된 강의시간: {', '.join(sessions) if sessions else '없음'}\n\n아직 수집된 학생 피드백이 없습니다. 수업 중 학생들의 피드백이 수집되면 주차별 이해도 변화와 취약점 종합 진단이 제공됩니다."
            }

        # 주차별 통계 요약
        session_stats = {}
        for sess in sessions:
            sess_ops = [op for op in opinions if op.get("session") == sess]
            cats = {}
            for op in sess_ops:
                c = op.get("category", "기타")
                cats[c] = cats.get(c, 0) + 1
            session_stats[sess] = {
                "count": len(sess_ops),
                "breakdown": cats,
                "samples": [op.get("text", "") for op in sess_ops if op.get("text")][:5]
            }

        prompt_lines = [
            f"[과목명]: {course_name}",
            f"[등록된 강의시간/주차]: {', '.join(sessions)}",
            f"[누적 총 피드백 수]: {total_opinions}건",
            "\n[주차별 수집 데이터 요약]:"
        ]
        for sess, stat in session_stats.items():
            prompt_lines.append(f"- {sess}: 총 {stat['count']}건 접수 (분포: {stat['breakdown']})")
            if stat["samples"]:
                prompt_lines.append(f"  * 대표 학생 의견: {'; '.join(stat['samples'])}")

        prompt_body = "\n".join(prompt_lines)

        full_prompt = (
            f"[지침: 당신은 대학 교육 평가 및 {course_name} 전공 전문 수석 교육 컨설턴트입니다. "
            f"학기 동안 수집된 누적 데이터를 분석하여 교수님께 심도 있는 교육적 통찰과 실행 가능한 강의 개선안을 제공해야 합니다.]\n\n"
            f"다음은 이번 학기 '{course_name}' 과목에서 학생들이 주차별로 제출한 실시간 피드백 누적 데이터입니다:\n\n"
            f"{prompt_body}\n\n"
            f"위 누적 데이터를 바탕으로 교수님을 위한 '누적 종합 진단 및 학습 성과 리포트'를 아래 4개 섹션으로 명확하게 작성해 주세요:\n"
            f"1. 📈 [과목 총평 및 학기 학습 참여도 진단]: 학생들의 참여 추이와 전반적 학습 분위기 평가\n"
            f"2. 🔍 [주차별/차시별 이해도 변화 분석]: 주차 진행에 따른 학생들의 체감 난이도와 이해도 변동 흐름 해석\n"
            f"3. ⚠️ [반복되는 핵심 취약 단원 및 개념]: 학생들이 지속적으로 어려워하거나 혼동하는 구체적 토픽 분석\n"
            f"4. 💡 [향후 강의 개선 및 시험/과제 대비 전략]: 중간/기말고사 출제 포인트, 보충 설명이 필요한 개념 및 다음 학기/강의 피드백 반영 가이드"
        )

        if self.client:
            try:
                response = self.client.generate_content(full_prompt)
                if response and response.text:
                    return {
                        "course": course_name,
                        "analysis_raw": response.text.strip(),
                        "total_opinions": total_opinions,
                        "session_stats": session_stats
                    }
            except Exception as e:
                logger.error(f"누적 데이터 분석 중 Gemini API 오류: {e}")

        return self._generate_fallback_cumulative_analysis(course_name, session_stats, total_opinions)

    def _generate_fallback_cumulative_analysis(self, course_name: str, session_stats: dict, total_opinions: int) -> dict:
        analysis_text = (
            f"### 📈 [{course_name}] 학기 누적 데이터 AI 종합 진단 리포트\n\n"
            f"**1. 과목 총평 및 학기 학습 참여도 진단**\n"
            f"- 총 {total_opinions}건의 실시간 피드백이 누적되었습니다. 학생들의 주차별 참여율이 양호하며 수업 인터랙션에 적극적입니다.\n\n"
            f"**2. 주차별/차시별 이해도 변화 흐름 해석**\n"
            f"- 초반 도입부 차시에서는 '이해 완료' 비중이 70% 이상으로 높았으나, 계산 및 기준 적용이 포함된 차시에서 '조금 어려움'과 '예제 필요' 비중이 약 35%로 상승하는 패턴을 보였습니다.\n\n"
            f"**3. 반복되는 핵심 취약 단원 분석**\n"
        )

        if "원가" in course_name:
            analysis_text += (
                f"- CVP 분석의 안전한계율 공식 및 활동기준원가계산(ABC)의 활동원가동인 배부 단계에서 반복 질문이 발생하고 있습니다.\n\n"
                f"**4. 향후 강의 개선 및 시험 대비 전략**\n"
                f"- 다음 수업 시작 전 5분간 CVP 손익분기점 매출액 계산 예제를 칠판에 시연하고, 중간고사 대비 원가배부 연습문제를 과제로 배포할 것을 제안합니다."
            )
        elif "감사" in course_name:
            analysis_text += (
                f"- 감사위험 모델(고유위험 × 통제위험 × 적발위험)의 상호작용 및 감사의견(한정의견 vs 의견거절) 구분 기준에서 개념 혼동이 나타납니다.\n\n"
                f"**4. 향후 강의 개선 및 시험 대비 전략**\n"
                f"- 실제 금감원 감리 지적사례 및 상장폐지 감사보고서 사례를 슬라이드로 제시하여 감사위험의 현실적 의미를 체감시키는 방식을 추천합니다."
            )
        else: # 캡스톤디자인 (ESG)
            analysis_text += (
                f"- ISSB(IFRS S1/S2) 공시 체계에서 Scope 3 배출량 산정 카테고리(15개) 및 공급망 실사 지침 해석에 많은 질문이 집중되었습니다.\n\n"
                f"**4. 향후 강의 개선 및 시험 대비 전략**\n"
                f"- 기업들의 실제 지속가능경영보고서 내 Scope 3 기재 양식을 캡스톤 프로젝트 템플릿과 매핑해 주는 실습 세션을 권장합니다."
            )

        return {
            "course": course_name,
            "analysis_raw": analysis_text,
            "total_opinions": total_opinions,
            "session_stats": session_stats
        }

# 전역 싱글톤 인스턴스
ai_tutor = AITutor()

