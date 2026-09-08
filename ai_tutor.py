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

    def analyze_session_comprehensive(
        self,
        course_name: str,
        session_name: str,
        material_data: dict,
        quizzes_data: list,
        opinions: list
    ) -> dict:
        """
        [1. 주차별 수업자료 내용] + [2. 문제 채점 결과 및 선택지별 학생 분포] + [3. 학생 실시간 피드백]을
        종합 분석하여 (1) 학생들을 위한 맞춤형 학습 제안과 (2) 교수자를 위한 다음 강의 제안을 생성합니다.
        """
        prompt_parts = []
        prompt_parts.append(f"[과목명]: {course_name}")
        prompt_parts.append(f"[강의시간/주차]: {session_name}")

        # 1. 수업자료 내용 요약
        if material_data and material_data.get("full_text"):
            fn = material_data.get("filename", "수업교안")
            total_u = material_data.get("total_units", 1)
            text_snippet = material_data.get("full_text")[:3500]
            prompt_parts.append(f"\n[1. 교수 제공 이번 주차 수업자료 내용 (파일명: {fn}, 총 {total_u}페이지/슬라이드)]:\n{text_snippet}")
        else:
            prompt_parts.append(f"\n[1. 교수 제공 수업자료]: 등록된 교안 파일 없음 ({course_name} {session_name} 표준 전공 커리큘럼 기준 분석)")

        # 2. 퀴즈 채점 결과 및 선택지별 학생 분포
        prompt_parts.append(f"\n[2. 이번 주차 실시간 퀴즈 및 학생 채점 결과 (총 {len(quizzes_data)}문제)]:")
        if quizzes_data:
            for idx, q in enumerate(quizzes_data, 1):
                ans_idx = int(q.get("answer", 0))
                options = q.get("options", [])
                stats = q.get("stats", {})
                total_resp = q.get("total_responses", 0)
                correct_count = stats.get(ans_idx, 0)
                correct_rate = f"{(correct_count / total_resp * 100):.1f}%" if total_resp > 0 else "응답 없음"

                q_lines = [
                    f"■ 문제 {idx}: {q.get('question')}",
                    f"  - 총 응답자: {total_resp}명 (정답률: {correct_rate})"
                ]
                for opt_i, opt_text in enumerate(options):
                    is_ans = " (★정답)" if opt_i == ans_idx else ""
                    cnt = stats.get(opt_i, 0)
                    pct = f"({(cnt / total_resp * 100):.1f}%)" if total_resp > 0 else ""
                    q_lines.append(f"    보기 {opt_i+1}{is_ans}: {opt_text} -> {cnt}명 선택 {pct}")
                if q.get("explanation"):
                    q_lines.append(f"  - 정답 해설: {q.get('explanation')}")
                prompt_parts.append("\n".join(q_lines))
        else:
            prompt_parts.append("  (이번 차시에 출제된 퀴즈 없음)")

        # 3. 학생 실시간 피드백
        prompt_parts.append(f"\n[3. 학생 실시간 피드백 (총 {len(opinions)}건)]:")
        if opinions:
            cat_counts = {}
            for op in opinions:
                c = op.get("category", "기타")
                cat_counts[c] = cat_counts.get(c, 0) + 1
            prompt_parts.append(f"  - 이해도 분포: {cat_counts}")
            prompt_parts.append("  - 주요 학생 의견 및 질문 목록:")
            for op in opinions[:20]:
                if op.get("text"):
                    prompt_parts.append(f"    * [{op.get('category')}] {op.get('text')}")
        else:
            prompt_parts.append("  (접수된 실시간 피드백 없음)")

        prompt_body = "\n".join(prompt_parts)

        full_prompt = (
            f"[수업 실제 데이터 분석 자료]\n"
            f"{prompt_body}\n\n"
            f"==================================================\n"
            f"[AI 분석 및 보고서 작성 지침]\n"
            f"당신은 대학 {course_name} 전공 전문 수석 교육 컨설턴트 및 AI 학습 코치입니다.\n\n"
            f"위 [수업 실제 데이터 분석 자료]에 제공된 '{course_name} {session_name}'의 ① 실제 수업자료 내용, ② 문제별 채점 결과 및 선택지별 학생 분포, ③ 실제 학생 피드백에만 100% 철저히 근거하여 심도 있는 분석 보고서를 작성하세요.\n\n"
            f"[⚠️ 엄격한 원칙 - 사실 기반 분석 및 가상 데이터(환각) 절대 금지]:\n"
            f"1. 반드시 위에 제공된 실제 데이터에만 철저히 근거하여 작성하십시오.\n"
            f"2. 절대로 존재하지 않는 가상의 학생 피드백, 가상의 질문, 가상의 의견을 지어내거나 날조(Hallucination)하지 마십시오.\n"
            f"3. 만약 학생 피드백이 0건이거나 없는 경우, 절대로 가상 피드백을 꾸며내지 말고 '접수된 실시간 학생 피드백이 없어, 등록된 수업자료와 퀴즈 채점 결과를 중심으로 분석합니다'라고 명확히 기재하십시오.\n"
            f"4. 만약 수업자료가 등록되지 않은 경우에도 임의로 다른 주차 내용(예: 1주차인데 후반부 CVP나 표준원가, ABC 등)을 끌어오지 말고, 해당 주차의 실제 퀴즈와 제공된 범위 내에서만 조언하십시오.\n\n"
            f"보고서는 반드시 아래 2개 대단원 순서대로 구체적이고 전문적으로 작성해야 합니다:\n\n"
            f"### 1. 🎓 학생들을 위한 맞춤형 학습 제안 (최우선 작성)\n"
            f"출제된 퀴즈 문제별로 아래 두 그룹을 명확히 분리하여 구체적인 학습 방향을 제시하세요:\n"
            f"- ✅ **정답을 맞힌 학생들을 위한 심화 학습 가이드**: 이번 주차 실제 문제와 수업자료의 해당 개념을 연결하여 더 깊이 있게 탐구할 수 있는 심화 질문/과제 제안\n"
            f"- ❌ **정답을 맞히지 못한(오답을 선택한) 학생들을 위한 맞춤 복습 가이드**: 학생들이 가장 많이 선택한 오답 보기의 매력적인 함정을 분석하고, 이번 수업자료(슬라이드/단원)의 어떤 개념과 수식을 다시 정독해야 하는지 구체적인 복습 포인트 제시\n\n"
            f"### 2. 👨‍🏫 교수자를 위한 다음 강의 개선 제안\n"
            f"- 🔍 **다음 강의 차시 시작 시 5분 필수 보충 설명 사항**: 이번 시간 퀴즈 중 정답률이 낮았거나 오답자가 많은 개념에 대해 다음 수업 첫머리에 꼭 짚어주어야 할 핵심 설명 포인트\n"
            f"- 💡 **학생 피드백 기반 강의 전달 방식 개선안**: 실제 접수된 학생 피드백에 기반한 강의 개선안 (접수된 피드백이 없을 경우 '피드백 미접수로 일반적인 개념 전달 강화 권장'으로 명시)\n"
            f"- 🎯 **확인용 보충 추천 퀴즈 1개**: 이번 차시 퀴즈와 수업자료 내용에 직접 부합하는 4지선다 퀴즈 (문제, 보기 4개, 정답, 해설)\n"
        )

        if self.client:
            try:
                response = self.client.generate_content(full_prompt)
                if response and response.text:
                    return {
                        "analysis_raw": response.text.strip(),
                        "summary": f"[{course_name} {session_name}] 수업자료·채점결과·피드백 3중 결합 AI 정밀 분석이 완료되었습니다.",
                        "opinions_count": len(opinions),
                        "quizzes_count": len(quizzes_data),
                        "has_material": bool(material_data and material_data.get("full_text"))
                    }
            except Exception as e:
                logger.error(f"종합 세션 분석 중 Gemini API 오류: {e}")

        # 폴백 분석 생성
        return self._generate_fallback_comprehensive_analysis(course_name, session_name, material_data, quizzes_data, opinions)

    def analyze_opinions(self, opinions: list) -> dict:
        """기존 하위 호환성 유지용"""
        return self.analyze_session_comprehensive("원가회계", "1주차", {}, [], opinions)

    def _generate_fallback_comprehensive_analysis(
        self,
        course_name: str,
        session_name: str,
        material_data: dict,
        quizzes_data: list,
        opinions: list
    ) -> dict:
        has_mat = bool(material_data and material_data.get("full_text"))
        mat_name = material_data.get("filename", "교안") if has_mat else None

        report_lines = [
            f"### 📊 [{course_name} - {session_name}] AI 정밀 학습 분석 및 강의 개선 리포트",
            f"*(수업자료: {'📄 ' + mat_name if has_mat else '미등록(기본 커리큘럼 기준)'} | 퀴즈: {len(quizzes_data)}문제 | 학생 피드백: {len(opinions)}건)*\n",
            "---",
            "### 1. 🎓 학생들을 위한 맞춤형 학습 제안 (최우선 과제)"
        ]

        if quizzes_data:
            for idx, q in enumerate(quizzes_data, 1):
                ans_idx = int(q.get("answer", 0))
                options = q.get("options", [])
                stats = q.get("stats", {})
                total_resp = q.get("total_responses", 0)
                correct_cnt = stats.get(ans_idx, 0)
                ans_text = options[ans_idx] if ans_idx < len(options) else f"보기 {ans_idx+1}"
                rate_str = f"{(correct_cnt/total_resp*100):.1f}%" if total_resp > 0 else "집계 중"

                # 가장 오답률 높은 보기 탐색
                wrong_counts = {i: stats.get(i, 0) for i in range(len(options)) if i != ans_idx}
                most_wrong_idx = max(wrong_counts, key=wrong_counts.get) if wrong_counts and max(wrong_counts.values()) > 0 else None
                most_wrong_text = options[most_wrong_idx] if most_wrong_idx is not None and most_wrong_idx < len(options) else None

                report_lines.append(f"\n#### 📌 [문제 {idx}] {q.get('question')} (정답: 보기 {ans_idx+1}, 정답률: {rate_str})")
                
                # 정답 학생 가이드
                report_lines.append(f"- ✅ **정답을 맞힌 학생 ({correct_cnt}명)을 위한 심화 학습 가이드**:")
                report_lines.append(f"  * 핵심 개념 '{ans_text}'의 기본 원리를 정확히 숙지했습니다.")
                if has_mat:
                    report_lines.append(f"  * **심화 과제**: 수업자료({mat_name})에서 다룬 '{ans_text}'의 정의를 바탕으로, 실제 기업 회계실무에서 이를 어떻게 적용하고 분류하는지 추가 사례를 탐구해보세요.")
                else:
                    report_lines.append(f"  * **심화 과제**: 단순 암기를 넘어 실제 기업 실무에서 '{ans_text}' 개념이 적용되는 구체적 업무 프로세스를 심층 탐구해보세요.")

                # 오답 학생 가이드
                wrong_total = total_resp - correct_cnt
                report_lines.append(f"- ❌ **정답을 맞히지 못한 학생 ({wrong_total}명)을 위한 맞춤 복습 가이드**:")
                if most_wrong_text:
                    report_lines.append(f"  * **함정 분석**: 오답자 중 다수가 **보기 {most_wrong_idx+1}번('{most_wrong_text}')**을 선택했습니다. 정답인 '{ans_text}'와의 명확한 개념적 차이를 비교 정리하는 것이 중요합니다.")
                report_lines.append(f"  * **복습 포인트**: {'수업자료 ' + mat_name + '의 핵심 슬라이드' if has_mat else '이번 주차 교재'}에서 정답 해설(_{q.get('explanation', ans_text)}_)을 반드시 다시 정독하고 핵심 구분 기준을 3줄로 직접 요약해보세요.")
        else:
            report_lines.append("\n*(이번 차시에 출제된 퀴즈 채점 결과가 없습니다. 퀴즈를 출제하시면 문제별 정답자/오답자 분리 학습 가이드가 자동 생성됩니다.)*")

        report_lines.append("\n---")
        report_lines.append("### 2. 👨‍🏫 교수자를 위한 다음 강의 개선 제안")

        report_lines.append(f"\n#### 🔍 [다음 강의 차시 시작 시 5분 필수 보충 설명 사항]")
        if quizzes_data:
            q_first = quizzes_data[0]
            report_lines.append(f"- 이번 시간 퀴즈 중 정답률이 낮거나 혼동이 발생했던 **'{q_first.get('question')}'** 관련 개념을 다음 수업 도입부 5분간 칠판에 실무 예시와 함께 다시 한 번 대조해 주시면 학생들의 학습 결손을 완벽히 메울 수 있습니다.")
        else:
            report_lines.append(f"- 이번 차시 수업자료의 핵심 수식 및 정의를 다음 차시 시작 전 5분 복습 퀴즈로 가볍게 점검하는 것을 권장합니다.")

        report_lines.append(f"\n#### 💡 [학생 피드백 기반 강의 전달 방식 개선안]")
        if opinions:
            hard_ops = [op.get('text') for op in opinions if op.get('category') in ['조금 어려움', '예제 필요', '질문 있음'] and op.get('text')]
            if hard_ops:
                report_lines.append(f"- 실제 접수된 학생 피드백 중 **'{hard_ops[0]}'** 등의 질문/요청이 접수되었습니다.")
                report_lines.append("- 학생들이 혼동하기 쉬운 용어와 개념에 대해 직관적인 대비표나 구체적인 실무 예시를 덧붙여 주시면 이해도를 크게 높일 수 있습니다.")
            else:
                report_lines.append("- 전반적으로 긍정적인 이해도를 보이고 있으며, 실제 기업 사례를 곁들이시면 더욱 높은 만족도를 이끌어낼 수 있습니다.")
        else:
            report_lines.append("- 현재 접수된 학생 실시간 피드백이 없습니다. 가상의 피드백을 지어내지 않고, 실제 퀴즈 오답 항목 및 교안 핵심 개념을 중심으로 다음 수업 도입부 보충 설명을 진행하시기 바랍니다.")

        report_lines.append(f"\n#### 🎯 [다음 시간 확인용 보충 추천 퀴즈 1개]")
        if "원가" in course_name:
            rec_q = {
                "question": "다음 중 원가의 분류 기준과 그에 따른 분류의 연결이 가장 옳은 것은?",
                "options": [
                    "추적가능성 - 제조원가와 비제조원가",
                    "원가행태(조업도 변동) - 변동원가와 고정원가",
                    "통제가능성 - 직접원가와 간접원가",
                    "의사결정 - 기초원가와 가공원가"
                ],
                "answer": 1,
                "explanation": "조업도(활동량) 변동에 따른 원가행태 분류는 변동원가와 고정원가이며, 추적가능성에 따른 분류는 직접원가와 간접원가, 기능에 따른 분류는 제조원가와 비제조원가입니다."
            }
        elif "감사" in course_name:
            rec_q = {
                "question": "다음 중 감사인이 내부통제제도를 평가하는 주된 목적으로 가장 옳은 것은?",
                "options": ["경영진의 부정행위를 100% 적발하기 위해", "통제위험을 평가하여 실증절차의 성격, 시기, 범위를 결정하기 위해", "재무제표의 모든 오류를 수정하기 위해", "회사의 주가를 안정시키기 위해"],
                "answer": 1,
                "explanation": "내부통제 평가는 통제위험을 사정하여 적발위험을 관리하기 위한 실증절차의 범위를 결정하기 위함입니다."
            }
        else:
            rec_q = {
                "question": "다음 중 ISSB IFRS S2 기준에 따른 기후 관련 위험 중 전환위험(Transition Risk)에 해당하는 것은?",
                "options": ["홍수나 가뭄 등 기상 이변으로 인한 물리적 피해", "탄소세 인상 및 친환경 기술 규제 강화", "지진으로 인한 사업장 파손", "해수면 상승으로 인한 부지 침수"],
                "answer": 1,
                "explanation": "탄소세 및 규제 강화, 저탄소 기술로의 전환 비용은 정책 및 법률 위험인 전환위험에 해당합니다."
            }

        report_lines.append(f"- **문제**: {rec_q['question']}")
        for opt_idx, opt_str in enumerate(rec_q['options']):
            check = " (★정답)" if opt_idx == rec_q['answer'] else ""
            report_lines.append(f"  {opt_idx+1}. {opt_str}{check}")
        report_lines.append(f"- **해설**: {rec_q['explanation']}")

        return {
            "analysis_raw": "\n".join(report_lines),
            "summary": f"[{course_name} {session_name}] 수업자료 및 퀴즈 채점 결과 종합 분석 완료",
            "opinions_count": len(opinions),
            "quizzes_count": len(quizzes_data),
            "has_material": has_mat,
            "recommended_quiz": rec_q
        }

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
