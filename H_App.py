# H_App.py
# Streamlit + Gemini + Google Docs 템플릿 복사/치환 + GAS(WebApp) 서식 적용 + Sheets 기록
#
# ✅ 이번 수정 반영
# 1) Sheets 컬럼 정렬 (A:H 고정)
#    A: 학년, B: 반, C: 번호, D: 학번, E: 이름, F: 컨설팅보고서, G: 담임선생님 조언, H: 생성시간
#    - F: 문구 "컨설팅 보고서"로 통일 + 하이퍼링크
#    - G: 문구 "조언"으로 통일 + 하이퍼링크
# 2) 디자인
#    - 시작 버튼 시인성 강화
#    - 우하단 개발자 이름 고정 표기
#    - 좌상단 학교 로고 + "언양고등학교" 링크(클릭 시 학교 홈페이지)

import json
import os
import random
import re
import tempfile
import time
from typing import Dict, Optional, Tuple

import requests
import streamlit as st
from google import genai
from google.genai import types
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


def rate_limit(key: str, limit: int, per_seconds: int) -> None:
    """
    간단 레이트리밋(세션 단위).
    key: 제한 그룹 이름
    limit: 허용 횟수
    per_seconds: 기간(초)
    """
    now = time.time()
    hist_key = f"_rl_{key}"
    hist = st.session_state.get(hist_key, [])

    # 기간 밖 기록 제거
    hist = [t for t in hist if now - t < per_seconds]

    if len(hist) >= limit:
        wait = int(per_seconds - (now - hist[0])) + 1
        st.error(f"요청이 너무 많습니다. {wait}초 후 다시 시도하세요.")
        st.stop()

    hist.append(now)
    st.session_state[hist_key] = hist


# =========================================================
# 0) 환경 설정 (당신 PC 환경에 맞게 수정)
# =========================================================


def load_oauth_client_secret_to_tempfile() -> str:
    if "GOOGLE_OAUTH_CLIENT_JSON" not in st.secrets:
        st.error("❌ secrets에 GOOGLE_OAUTH_CLIENT_JSON이 없습니다.")
        st.stop()

    raw = st.secrets["GOOGLE_OAUTH_CLIENT_JSON"]
    obj = json.loads(raw)

    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    tf.write(json.dumps(obj).encode("utf-8"))
    tf.close()
    return tf.name


OAUTH_CLIENT_SECRET_FILE = load_oauth_client_secret_to_tempfile()


# 템플릿 문서 ID (보고서 / 지도방침 분리 권장)
TEMPLATE_REPORT_DOC_ID = "1HPzXRHgK1k6sx3f0IlXa4E2WLiOz2bDtqnxsAhbbdjo"
TEMPLATE_GUIDE_DOC_ID = "1183Mnqp676B7bn1y2aDdqhSGHeZX_HPx1DscgP_ZNTs"

# 저장 폴더 ID (비우면 내 드라이브 루트)
DRIVE_FOLDER_ID_REPORT = "1jb60S7fibE-Acz9f8vZZt-4r7-fTLwjp"
DRIVE_FOLDER_ID_GUIDE = "1jb60S7fibE-Acz9f8vZZt-4r7-fTLwjp"

# 스프레드시트 기록
SHEETS_ID = "1cwJ4Lf_XE5sWDNATHBTzhoeNgFM5jBV-Tj4Qx7GyrL0"
SHEETS_TAB = "컨설팅 보고서"

# Gemini Key
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

# GAS Web App (자동 서식 적용)
GAS_WEBAPP_URL = st.secrets["GAS_WEBAPP_URL"]
GAS_TOKEN = st.secrets["GAS_TOKEN"]


AUTO_GAS_FORMAT_DEFAULT = False  # 기본은 안정적으로 OFF

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
]

MODEL_REPORT = "gemini-2.5-pro"
MODEL_SUMMARY = "gemini-2.5-flash"
MODEL_GUIDE = "gemini-2.5-pro"


# =========================================================
# 0-1) UI/브랜딩 설정 (여기만 바꾸면 됨)
# =========================================================
SCHOOL_NAME = "언양고등학교"
SCHOOL_HOMEPAGE_URL = (
    "https://school.use.go.kr/eonyang-h"  # TODO: 언양고 홈페이지 주소로 교체
)
LOGO_FILE = "언양고 로고.png"  # 앱 파일과 같은 폴더에 두면 표시됨(없어도 동작)
DEVELOPER_NAME = "언양고 교사 INOMA"  # TODO: 개발자 이름 입력


# =========================================================
# 1) Streamlit UI
# =========================================================

st.set_page_config(page_title="학생부 컨설팅 보고서", layout="wide")

import streamlit as st

ACCESS_CODE = st.secrets.get("ACCESS_CODE", "")

if ACCESS_CODE:
    code = st.text_input("테스터 코드", type="password")
    if code != ACCESS_CODE:
        st.warning("접근이 제한된 테스트 버전입니다. 테스터 코드를 입력하세요.")
        st.stop()


# ---- CSS: 버튼/헤더/푸터(개발자명) ----
st.markdown(
    """
    <style>
      /* 상단 여백 살짝 */
      .block-container { padding-top: 1.8rem !important; }

      /* 시작 버튼 시인성 강화(전역 st.button에 적용됨) */
      div[data-testid="stButton"] > button {
        font-size: 20px !important;
        font-weight: 800 !important;
        padding: 0.9rem 1.1rem !important;
        border-radius: 16px !important;
        box-shadow: 0 10px 22px rgba(0,0,0,0.18) !important;
        border: 0 !important;
        background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%) !important;
        color: white !important;
      }
      div[data-testid="stButton"] > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 14px 28px rgba(0,0,0,0.22) !important;
        filter: brightness(1.03);
      }

      /* 우하단 개발자 표기 */
      .dev-footer {
        position: fixed;
        bottom: 12px;
        right: 16px;
        font-size: 15px;
        color: #94a3b8;
        opacity: 0.88;
        z-index: 999;
        user-select: none;
      }

      /* 좌상단 학교 브랜딩 */
      .school-brand {
        display: inline-flex;
        align-items: center;
        gap: 10px;
        text-decoration: none !important;   /* ✅ 밑줄 제거 */
        padding-top: 6px;                   /* ✅ 잘림 느낌 제거 */
      }
      .school-brand img {
        height: 34px;
        width: 34px;
        object-fit: contain;
        display: block;
      }
      .school-brand .name {
        font-weight: 800;
        font-size: 16px;
        color: #0f172a;
        line-height: 1.2;                   /* ✅ 위아래 잘림 방지 */
        text-decoration: none !important;   /* ✅ 밑줄 제거 */
      }
      
        /* 링크 기본 스타일 완전 제거 */
        .school-brand:link,
        .school-brand:visited,
        .school-brand:hover,
        .school-brand:active {
            text-decoration: none !important;
            color: inherit;
        } 
      @media (prefers-color-scheme: dark) {
        .school-brand .name { color: #e2e8f0; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)

# 우하단 개발자 이름
st.markdown(
    f'<div class="dev-footer">© 2025 · Designed & Developed by 언양고 교사 INOMA</div>',
    unsafe_allow_html=True,
)

# 좌상단 로고 + 학교명(클릭 링크)
logo_path = os.path.join(os.path.dirname(__file__), LOGO_FILE)
if os.path.exists(logo_path):
    st.markdown(
        f"""
        <div style="margin-bottom: 10px;">
          <a class="school-brand" href="{SCHOOL_HOMEPAGE_URL}" target="_blank" rel="noopener noreferrer">
            <img src="data:image/png;base64,{__import__("base64").b64encode(open(logo_path,"rb").read()).decode("utf-8")}" />
            <span class="name">{SCHOOL_NAME}</span>
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"""
        <div style="margin-bottom: 10px;">
          <a class="school-brand" href="{SCHOOL_HOMEPAGE_URL}" target="_blank" rel="noopener noreferrer">
            <span class="name">{SCHOOL_NAME}</span>
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

auto_gas_format = st.sidebar.toggle(
    "자동 서식 적용(GAS)",
    value=AUTO_GAS_FORMAT_DEFAULT,
    help="ON이면 문서 생성 직후 GAS 자동 서식을 '시도'합니다. 실패해도 보고서 생성은 계속됩니다.",
)

st.markdown(
    """
    <div style="text-align:center; margin-top:14px; margin-bottom:18px;">
        <div style="font-size:44px; font-weight:800;">🌟 너는 별이다</div>
        <div style="margin-top:6px; color:#475569; font-size:22px; font-weight:700;">
            고1 학생부 AI 컨설팅 앱
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if not GEMINI_API_KEY:
    st.error("⚠️ GEMINI_API_KEY 환경 변수가 설정되지 않았습니다.")
    st.stop()

client = genai.Client(api_key=GEMINI_API_KEY)

# =========================================================
# 2) 재시도(백오프)
# =========================================================


def _sleep_backoff(attempt: int, base: float = 2.0, cap: float = 60.0) -> None:
    delay = min(cap, base * (2**attempt))
    delay = delay * (0.6 + random.random() * 0.8)
    time.sleep(delay)


def _is_retryable_gemini_error(e: Exception) -> bool:
    s = str(e).lower()
    return any(
        k in s
        for k in [
            "429",
            "rate",
            "quota",
            "resource exhausted",
            "503",
            "overload",
            "unavailable",
            "504",
            "deadline",
            "timeout",
        ]
    )


def _is_retryable_http_error(e: HttpError) -> bool:
    status = None
    try:
        status = e.resp.status
    except Exception:
        pass
    return status in [429, 500, 502, 503, 504]


def execute_with_retry(fn, max_retries: int = 6, label: str = "API"):
    for attempt in range(max_retries):
        try:
            return fn()
        except HttpError as e:
            if _is_retryable_http_error(e) and attempt < max_retries - 1:
                st.warning(f"⚠️ {label} 재시도 ({attempt+1}/{max_retries})")
                _sleep_backoff(attempt)
                continue
            raise


# =========================================================
# 3) Google OAuth & 서비스
# =========================================================


def get_google_services():
    """
    Streamlit Cloud / 서버 환경용
    - Service Account 기반 Google Docs / Drive / Sheets 인증
    """
    import json

    import streamlit as st
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    if "GOOGLE_SERVICE_ACCOUNT_JSON" not in st.secrets:
        st.error("❌ GOOGLE_SERVICE_ACCOUNT_JSON 이 Secrets에 없습니다.")
        st.stop()

    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])

    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=[
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/spreadsheets",
        ],
    )

    drive = build("drive", "v3", credentials=creds)
    docs = build("docs", "v1", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)

    return drive, docs, sheets


# =========================================================
# 4) Drive: 템플릿 복사 + 폴더 이동
# =========================================================


def copy_template(
    drive_service, template_id: str, title: str, folder_id: str = ""
) -> str:
    copied = execute_with_retry(
        lambda: drive_service.files()
        .copy(
            fileId=template_id,
            body={"name": title},
            supportsAllDrives=True,
        )
        .execute(),
        label="Drive Copy",
    )
    file_id = copied.get("id")
    if not file_id:
        raise RuntimeError("템플릿 복사 실패: id 없음")

    folder_id = (folder_id or "").strip()
    if folder_id:
        meta = execute_with_retry(
            lambda: drive_service.files()
            .get(fileId=file_id, fields="parents", supportsAllDrives=True)
            .execute(),
            label="Drive Get Parents",
        )
        prev_parents = ",".join(meta.get("parents", []))
        execute_with_retry(
            lambda: drive_service.files()
            .update(
                fileId=file_id,
                addParents=folder_id,
                removeParents=prev_parents,
                fields="id, parents",
                supportsAllDrives=True,
            )
            .execute(),
            label="Drive Move Folder",
        )

    return file_id


# =========================================================
# 5) Docs: placeholder 관리
# =========================================================


def _doc_contains_text(doc_json: dict, needle: str) -> bool:
    content = doc_json.get("body", {}).get("content", [])
    for el in content:
        para = el.get("paragraph")
        if not para:
            continue
        for pe in para.get("elements", []):
            tr = pe.get("textRun", {})
            txt = tr.get("content", "")
            if needle in txt:
                return True
    return False


def ensure_placeholders_exist(
    docs_service, doc_id: str, placeholders: Dict[str, str]
) -> None:
    """문서 내 플레이스홀더가 없으면 '문서 끝'에 삽입(보험)."""
    doc = execute_with_retry(
        lambda: docs_service.documents().get(documentId=doc_id).execute(),
        label="Docs Get",
    )
    missing = [ph for ph in placeholders.keys() if not _doc_contains_text(doc, ph)]
    if not missing:
        return

    content = doc.get("body", {}).get("content", [])
    end_index = content[-1].get("endIndex") if content else 1
    if end_index is None:
        end_index = 1

    insert_text = "\n"
    for ph in missing:
        title = placeholders.get(ph, ph)
        insert_text += f"\n[{title}]\n{ph}\n"
    insert_text += "\n"

    reqs = [{"insertText": {"location": {"index": end_index - 1}, "text": insert_text}}]

    execute_with_retry(
        lambda: docs_service.documents()
        .batchUpdate(documentId=doc_id, body={"requests": reqs})
        .execute(),
        label="Docs Insert Placeholder",
    )


def batch_replace_all_text(
    docs_service, doc_id: str, replace_map: Dict[str, str]
) -> None:
    reqs = []
    for k, v in replace_map.items():
        reqs.append(
            {
                "replaceAllText": {
                    "containsText": {"text": k, "matchCase": True},
                    "replaceText": v or "",
                }
            }
        )
    if not reqs:
        return

    execute_with_retry(
        lambda: docs_service.documents()
        .batchUpdate(documentId=doc_id, body={"requests": reqs})
        .execute(),
        label="Docs ReplaceAllText",
    )


def remove_debug_tokens_after_format(docs_service, doc_id: str) -> None:
    """GAS 서식 적용 후 보기 싫은 토큰 제거(보고서+담임템플릿 공용)."""
    batch_replace_all_text(
        docs_service,
        doc_id,
        {
            # 공용
            "[[HR]]": "",
            "=== 본문 시작 ===": "",
            # 보고서 템플릿
            "{{REPORT_ANCHOR}}": "",
            # 담임 템플릿
            "{{GUIDE_ANCHOR}}": "",
            "[[NOTES_START]]": "",
            "[[NOTES_END]]": "",
        },
    )


# =========================================================
# 6) Gemini 생성
# =========================================================


def gemini_generate_text_with_retry(
    model: str, prompt: str, pdf_bytes: Optional[bytes], max_retries: int = 6
) -> str:
    contents = [prompt]
    if pdf_bytes:
        pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
        contents.append(pdf_part)

    cfg = types.GenerateContentConfig(
        temperature=0.35,
        max_output_tokens=8192 if model.endswith("pro") else 4096,
    )

    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=model, contents=contents, config=cfg
            )
            text = (resp.text or "").strip()
            if not text:
                raise RuntimeError("Gemini 응답이 비었습니다.")
            return text
        except Exception as e:
            last_err = e
            if _is_retryable_gemini_error(e) and attempt < max_retries - 1:
                st.warning(f"⚠️ Gemini 재시도 ({attempt+1}/{max_retries})")
                _sleep_backoff(attempt)
                continue
            raise RuntimeError(f"Gemini 실패: {e}") from e

    raise RuntimeError(f"Gemini 실패(최종): {last_err}")


# =========================================================
# 7) 본문 숫자목록 방지(후처리) — 헤딩 보호
# =========================================================


def is_heading_line(line: str) -> bool:
    s = line.strip()
    if not re.match(r"^\d+(-\d+){0,2}\.\s+\S+", s):
        return False
    if len(s) > 40:
        return False
    if s.endswith(("다.", "요.", ".")):
        return False
    return True


def sanitize_numbered_lists(text: str) -> str:
    lines = text.splitlines()
    processed = []
    for line in lines:
        stripped = line.strip()

        # ✅ 헤더는 무조건 보호
        if is_heading_line(stripped):
            processed.append(stripped)
            continue

        # ❌ 일반 숫자 목록만 변환
        if re.match(r"^\d+\.\s+", stripped):
            body = stripped.split(".", 1)[1].strip()
            processed.append(f"- {body}")
        else:
            processed.append(line)
    return "\n".join(processed)


# =========================================================
# 8) 담임조언 분량: 9000바이트 내에서 문장 완결 우선
# =========================================================


def trim_korean_text_safely(text: str, max_utf8_bytes: int = 9000) -> str:
    t = (text or "").strip()
    if not t:
        return t
    if len(t.encode("utf-8")) <= max_utf8_bytes:
        return t

    b = t.encode("utf-8")[:max_utf8_bytes]
    return b.decode("utf-8", errors="ignore").strip()


# =========================================================
# 9) 프롬프트
# =========================================================


def build_stage1_prompt(student_name: str, notes: str) -> str:
    notes_block = notes.strip() if notes.strip() else "(담임 메모 없음)"
    return (
        f"""
당신은 경력 20년의 고등학교 진학지도교사입니다.
입력은 한 학생의 ‘자기평가서(PDF) 내용’과 담임교사의 ‘중요 메모(추가 기재사항)’입니다.
이 정보를 바탕으로 학생부종합전형(학종)에 맞는 최적의 진학 컨설팅 보고서를 작성하십시오.

[담임 메모(보고서에는 직접 노출하지 않되, 내용에 반영)]
{notes_block}


[🔴 GAS 자동 서식 규칙 — 반드시 준수]
0) 출력은 ‘순수 텍스트’만. JSON/코드블록/설명문/서론 금지.
1) 제목(헤딩)은 오직 아래 3종의 형식만 허용.(아래 형식과 보고서 목차를 종합해 생성)
   - 1. 제목
   - 1-1. 제목
   - 1-1-1. 제목
2) 본문 내부에서는 절대 ‘1. 2. 3.’ 같은 숫자목록 금지.
   - 각 문단은 문단 내용을 대표하는 키워드를 (말머리) 형태의 말머리로 시작
3) 전공 추천/도서 추천/AI추천 항목은 번호 금지.
   - 전공 추천 각 항목 앞: (🧑‍🎓🧬🔭AI추천) 굵은 빨간 글씨로 표시
   - 도서 추천 각 항목 앞: (🔖AI추천) 굵은 빨간 글씨로 표시
   - AI추천 각 항목 앞: (🤖AI추천)
4) (헤딩 1. 단위) 끝날 때마다 다음 토큰을 ‘단독 한 줄’로 넣을 것:
   [[HR]]
   ※ 이 토큰은 문서에서 '페이지 나눔'으로 변환되며 최종 문서에는 남지 않는다.
5) 문단과 문단 사이는 빈 줄 1개(줄바꿈 2번).
6) 학생 이름은 "{student_name}". 호칭은 ‘학생’ 또는 학생 이름으로 통일.
7) 존댓말. 과한 미화 금지. 구체적 실행 중심.
8) 모든 말머리는 굵은 빨간 글씨
""".strip()
        + f"""


[보고서 목차(반드시 포함)]
1. 학생을 위한 한마디 (감성적 격려와 총평, 300자 이내)
2. 컨설팅 종합 분석 요약
3. 대학 전공 추천 (이유 포함)
4. 1학년 활동 문제점 및 보완 전략
5. 추천 도서 (고전 2권 + 전공 적합 도서 2~3권)
6. 창체 영역별 상세 컨설팅
  6-1. 자율활동
  6-2. 진로활동
  6-3. 동아리활동
  6-4. 봉사활동
7. 2학년 교과별 전략/수업 태도 개선 전략
8. 인성 및 행동특성 종합 의견


[추가 메모]
--------------------------------
1. 학생을 위한 한마디
--------------------------------
학생 이름을 1회 포함하여 표현
전체 입력 내용을 종합한 총평을 학생을 격려, 따뜻하고 감성적인 말과 함께 제시. 
최대한 감성적이고 문학적인 표현을 섞어 전해줘. 문학/시 작품 인용하여 표현하는 거 권장.
단, 한글 400자 이상을 넘지 않도록 분량 조절(1200바이트)
글자가 넘지 않으면서도 자연스럽게 분량에 맞춰 글을 완성




--------------------------------
2. 컨설팅 종합 분석
--------------------------------
2-1. 최상의 대입 준비를 위한 학생의 학교생활기록부(학생부) 스토리 전략을 제시할 것.
     - 이 학생의 핵심 키워드, 장점, 전공적합성, 성장 스토리를 3~5문장 정도로 요약.
2-2. ‘1학년 활동 종합 → 2학년 활동 컨설팅 → 3학년 활동 컨설팅’ 흐름으로 정리할 것.
     - 1학년에서 이미 형성된 방향성 요약
     - 2학년에서 어떤 활동을 추가/심화해야 하는지 제안
     - 3학년에서 마무리·정리해야 할 포인트 제안
2-3. 3년 동안의 활동이 최종 진학/진로 희망을 달성할 수 있도록,
     하나의 스토리로 유기적으로 연결된 학생부 스토리를 제안할 것.
2-4. PDF 자기평가서에 정보가 부족한 부분이나 비어 있는 영역이 있다면
     (🤖AI추천) 말머리를 달고, 구체적인 활동/내용을 제안할 것.






--------------------------------
3. 대학 전공 추천
--------------------------------
3-1. 창의적 체험활동(창체)와 전체 내용을 분석하여,
     학생에게 맞는 최상의 대학 전공을 1, 2, 3순위까지 추천하고,
     각 전공을 추천하는 이유를 구체적으로 설명할 것.
3-2. 학생이 자기평가서에 희망 진로를 직접 작성한 경우,
     - 그 진로와 니가 추천한 전공과 어떻게 일치하거나 다른지 비교·분석할 것.






--------------------------------
4. 1학년 활동 문제점 및 보완 전략
--------------------------------
4-1. 1학년 활동 중에서 학종 관점에서 보았을 때의 문제점·아쉬운 점을 지적할 것.
4-2. 보완이 필요한 영역(예: 전공연계성, 독서, 봉사, 심화탐구 등)을 제시하고,
     각 영역별로 구체적인 대안을 제안할 것.
4-4. 니가 제시하는 대안은 반드시 (🤖AI추천) 말머리를 달아줄 것.






--------------------------------
5. 추천 도서
--------------------------------
5-1. 1학년 때 보완해야할 추천 고전도서: 학생의 종합적 특성을 고려했을 때,
     꼭 읽어보기를 권하고 싶은 ‘고전 교양도서’ 2권을 추천 이유와 함께 제시할 것.
5-2. 추천 전공도서: 전공과 관련된 고1 수준의 교양 서적 2-3권 추천
     + 활동 내용과 직접적으로 연관된 교양 책,
     + 활동 내용과 직접적으로 연관된 참고 서적을 제시하고,
     각각에 대해 추천 사유를 함께 쓸 것.
5-3. 2학년 때 읽어야할 추천도서: 1학년 활동과 자연스럽게 연계되면서,
     1학년보다 한 단계 높은 수준의 전공 서적 또는 교양 서적을 추천할 것.
     - 2~4권 정도, 각 도서마다 활동·전공과의 연결 이유를 짧게 서술.






--------------------------------
6-1. 창의적 체험활동#1 자율활동
--------------------------------
총 3-4개의 활동을 정리할 것.
자기평가서에 이미 나온 내용을 우선하여, 중요한 것부터 우선순위를 정해 컨설팅할 것.
각 활동은 아래 구조로 서술할 것.
     - 지적 호기심 발동: 어떤 문제의식·궁금증에서 출발했는지
     - 탐구 활동: 무엇을, 어떻게, 얼마나, 누구와 탐구했는지
     - 후속 활동/배운 점/성장: 그 결과 어떤 변화, 성장, 후속 활동이 있었는지
활동 하나당 관련 추천 도서 1~2권을 제시하고, 해당 활동과 어떻게 연결되는지 추천 이유를 함께 제시할 것.
자기평가서에 자율활동 관련 내용이 부족하거나 없다면, (🤖AI추천) 말머리를 달고 대체·보완 가능한 활동을 제안할 것.
자율활동 내용은 진로활동, 동아리활동, 봉사활동, 교과 세특과 서로 유기적으로 연결되도록 설계할 것.






--------------------------------
6-2. 창의적 체험활동#2 진로활동
--------------------------------
진로활동도 자율활동과 동일한 활동 갯수, 동일한 서술방식(지적 호기심 발동-탐구 활동-후속 활동 구조), 추천도서로 컨설팅할 것.
자율/진로/동아리/봉사/교과세특이 한 줄기 스토리로 이어지도록, 진로활동의 역할과 위치를 분명하게 제시할 것.






--------------------------------
6-3. 창의적 체험활동#3 동아리활동
--------------------------------
동아리 활동도 자율활동, 진로활동 동일한 방식으로 컨설팅할 것. 추천도서도 제안
동아리 활동이 전체 창체 활동과 교과 세특, 그리고 희망 전공과 어떻게 연결되는지를 명확하게 설명할 것.
자기평가서에 진로활동 관련 내용이 부족하거나 없다면, (🤖AI추천) 말머리를 달고 대체·보완 가능한 활동을 제안할 것.


--------------------------------
6-4. 창의적 체험활동#4 봉사활동
--------------------------------
자기평가서에 봉사활동 내용이 없거나 매우 부족하면, (🤖AI추천) 말머리를 달고, 전공 및 인성과 연결 가능한 봉사활동을 제안할 것.
봉사활동 내용이 있다면, 다른 활동(자율/진로/동아리/교과) 및 진로 목표와 연결하여 의미를 재구성할 것.
봉사활동 역시 전체 창체·교과 세특과 하나의 스토리로 이어지도록 설계할 것.




--------------------------------
7. 2학년 교과별 전략 / 수업 태도 개선 전략
--------------------------------
자기평가서에 2학년 선택과목 내용이 없거나 매우 부족하면,(🤖AI추천) 말머리를 달고, 전공과 연결되는 고등학교 과목 제안, 이유설명
입력된 고등학교 2학년 선택과목중 3개를 선택해 추천하는 활동 내용 제시
2학년 교과 활동 추천할 때 관련된 추천 도서(고전+전공+교양)를 2-3권씩 같이 제시
집중력있고, 끈기있는, 성실한 수업 태도 강조




--------------------------------
8. 인성 및 행동특성 종합 의견
--------------------------------
위 모든 자료를 종합하여, 안성분야에 대해 분석, 총평
최소 2개에서 최대 4개의 문단으로 구성할 것.




[마지막 주의사항]
- 학생을 비현실적으로 미화하지 말고, 자기평가서 내용과 어긋나지 않는 선에서 구체적으로 보완·제안할 것.
- 전체 문장은 매끄럽고 전문적인 어투의 존댓말로 작성할 것.


""".strip()
    )


def ensure_report_complete(report_md: str, student_name: str) -> str:
    required_sections = [
        "1. 학생을 위한 한마디",
        "2. 컨설팅 종합 분석",
        "3. 대학 전공 추천",
        "4. 1학년 활동 문제점 및 보완 전략",
        "5. 추천 도서",
        "6-1. 창의적 체험활동#1 자율활동",
        "6-2. 창의적 체험활동#2 진로활동",
        "6-3. 창의적 체험활동#3 동아리활동",
        "6-4. 창의적 체험활동#4 봉사활동",
        "7. 2학년 교과별 전략",
        "8. 인성 및 행동특성 종합 의견",
    ]

    missing = [s for s in required_sections if s not in report_md]
    if not missing:
        return report_md

    prompt = f"""
아래 보고서는 중간에 끊겼습니다.
누락된 항목만 이어서 작성하십시오.
이미 작성된 내용은 반복하지 말고,
다음 항목부터 계속 작성하세요.

누락 항목:
{", ".join(missing)}

[기존 보고서]
{report_md}
"""

    continuation = gemini_generate_text_with_retry(MODEL_REPORT, prompt, None)

    return report_md.strip() + "\n\n" + continuation.strip()


def build_stage2_prompt(report_md: str) -> str:
    return f"""
아래 컨설팅 보고서를 담임교사가 빠르게 파악할 수 있도록 요약하십시오.

[요약 규칙]
- 핵심만, 과장 없이
- '강점 5개 / 보완점 5개 / 즉시 실행 5개'
- 마지막에 "학생부 스토리 한 문장"
- Markdown
- 목록은 하이픈(-)만(숫자목록 금지)

[원문]
{report_md}
""".strip()


def build_stage3_homeroom_prompt(report_md: str, summary_md: str) -> str:
    return f"""

학생의 전체 컨설팅 결과를 토대로 담임교사가 학생을 지도할 때 기울여야할 지도 방침을 작성.
컨설팅 보고서 요약 + 지도 조언 + 담임선생님을 향한 따뜻하고 공감어린 격려와 위로를 섞어 작성.
무리한 미화 없이 학생부 흐름을 하나의 스토리로 연결.
창체-교과-독서-인성이 서로 맞물리도록.
가급적 9000바이트(한글 3000자 내외) 기준으로 '완결감 있게' 작성(문장 중간 절단 금지, 반드시 맺음말).




[작성 방향]
- 단순한 조언 나열이 아니라,
  학생의 학생부 흐름(창체-교과-독서-인성)을 하나의 이야기로 엮어 서술할 것
- 무리한 미화는 피하고, 실제 담임교사가 공감할 수 있는 현실적인 어조 유지
- 학생의 강점은 어떻게 더 살릴지,
  보완점은 어떤 방향으로 지도하면 좋을지 구체적으로 제시
- 진학 전략뿐 아니라,
  담임교사를 향한 따뜻하고 공감 어린 격려와 위로의 메시지를 자연스럽게 포함할 것




[내용 구성 권장]
1. 학생 전체 흐름에 대한 담임 관점의 종합 해석
2. 교과·비교과·독서·인성이 맞물리는 지도 포인트
3. 진로·진학 지도 시 특히 유의할 점
4. 담임교사를 향한 공감과 응원의 말




[주의]
- 학생에게 직접 말하는 형식이 아니라,
  ‘담임교사를 위한 내부 지도 문서’로 작성할 것
- 훈계조, 평가조 문체는 지양할 것




[요약]
{summary_md}

[원문]
{report_md}

[출력 규칙]
- Markdown
- 목록은 하이픈(-)만(숫자목록 금지)
""".strip()


# =========================================================
# 10) GAS 호출
# =========================================================


def call_gas_auto_format(doc_id: str) -> None:
    try:
        params = {"docId": doc_id, "token": GAS_TOKEN}
        r = requests.get(GAS_WEBAPP_URL, params=params, timeout=10)

        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")

        ct = r.headers.get("Content-Type", "")
        if "application/json" not in ct:
            raise RuntimeError(f"Non-JSON response: {ct}")

        data = r.json()
        if not data.get("ok", False):
            raise RuntimeError("GAS ok=false")

        st.info("ℹ️ (참고) 자동 서식 적용 시도 완료")

    except Exception:
        st.warning(
            "⚠️ 자동 서식 적용은 건너뛰었습니다.\n"
            "문서 상단 메뉴 ‘⚙ 보고서 서식 → ✅ 본문 서식 적용’을 눌러주세요."
        )


# =========================================================
# 11) Sheets 기록 (A열부터 정확히)
# =========================================================


def make_hyperlink_formula(url: str, label: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    u = u.replace('"', '""')
    label = (label or "").replace('"', '""')
    return f'=HYPERLINK("{u}","{label}")'


def write_row_to_sheet_from_A6(sheets_service, values_a_to_g: list) -> None:
    """
    A6부터 아래로 내려가며 '가장 위의 빈 행'을 찾아
    A~G에 values_a_to_g(7개)를 쓰고, H에는 생성 시간을 기록한다.

    values_a_to_g = [grade, klass, number, student_num5, name, report_link, guide_link]
    """
    if not SHEETS_ID.strip():
        return

    read_range = f"{SHEETS_TAB}!A6:H1005"
    resp = execute_with_retry(
        lambda: sheets_service.spreadsheets()
        .values()
        .get(spreadsheetId=SHEETS_ID, range=read_range, majorDimension="ROWS")
        .execute(),
        label="Sheets Read",
    )
    rows = resp.get("values", [])

    target_offset = None
    for i, r in enumerate(rows):
        a = (r[0] if len(r) > 0 else "").strip()
        if a == "":
            target_offset = i
            break

    if target_offset is None:
        target_offset = len(rows)

    target_row = 6 + target_offset
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")

    write_values = values_a_to_g[:7] + [created_at]  # A~H (8칸)

    update_range = f"{SHEETS_TAB}!A{target_row}:H{target_row}"
    body = {"values": [write_values]}

    execute_with_retry(
        lambda: sheets_service.spreadsheets()
        .values()
        .update(
            spreadsheetId=SHEETS_ID,
            range=update_range,
            valueInputOption="USER_ENTERED",
            body=body,
        )
        .execute(),
        label="Sheets Write",
    )


def parse_student_num5(num5: str):
    if not re.fullmatch(r"\d{5}", num5 or ""):
        return "", "", ""
    grade = num5[0]
    klass = str(int(num5[1:3]))
    number = str(int(num5[3:5]))
    return grade, klass, number


# =========================================================
# 12) 제목/학번
# =========================================================


def normalize_student_num(raw: str) -> str:
    s = re.sub(r"\D", "", (raw or "").strip())
    return s[:5] if len(s) >= 5 else ""


def make_doc_titles(student_num5: str, student_name: str) -> Tuple[str, str]:
    base = f"{student_num5}_{student_name}"
    return base, f"{base}_담임교사지도방침"


# =========================================================
# 13) UI 입력
# =========================================================

col1, col2 = st.columns(2)
with col1:
    student_num = st.text_input("학번(예: 10201) — 5자리 필수", value="")
with col2:
    student_name = st.text_input("학생 이름", value="")

uploaded_pdf = st.file_uploader("학생 자기평가서(PDF) 업로드", type=["pdf"])

notes = st.text_area(
    "담임교사 추가 기재사항(중요 메모) — 보고서에는 숨김/지도방침에만 출력",
    height=180,
    placeholder="학생의 맥락(학습태도/희망진로/정서·생활/특이사항) 중 지도방침에 반영할 핵심만 적어주세요.",
)

run = st.button("🚀 학생부 컨설팅 시작")
if run:
    rate_limit("generate_report", limit=2, per_seconds=60)


# =========================================================
# 14) 실행
# =========================================================

if run:
    student_num5 = normalize_student_num(student_num)
    if not student_num5:
        st.error("학번은 숫자 5자리로 입력하세요. (예: 10201)")
        st.stop()

    if not student_name.strip():
        st.error("학생 이름을 입력하세요.")
        st.stop()

    if not uploaded_pdf:
        st.error("PDF를 업로드하세요.")
        st.stop()

    pdf_bytes = uploaded_pdf.read()
    grade, klass, number = parse_student_num5(student_num5)

    with st.spinner("Google 서비스 연결 중..."):
        try:
            drive_service, docs_service, sheets_service = get_google_services()
        except Exception as e:
            st.error(f"Google OAuth/서비스 연결 실패: {e}")
            st.stop()

    with st.spinner("1단계: 컨설팅 보고서 생성 중..."):
        try:
            p1 = build_stage1_prompt(student_name.strip(), notes)
            report_md = gemini_generate_text_with_retry(MODEL_REPORT, p1, pdf_bytes)
            report_md = ensure_report_complete(report_md, student_name.strip())
            report_md = sanitize_numbered_lists(report_md)

        except Exception as e:
            st.error(f"1단계 실패: {e}")
            st.stop()

    with st.spinner("2단계: 보고서 요약 생성 중..."):
        try:
            p2 = build_stage2_prompt(report_md)
            summary_md = gemini_generate_text_with_retry(MODEL_SUMMARY, p2, None)
            summary_md = sanitize_numbered_lists(summary_md)
        except Exception as e:
            st.error(f"2단계 실패: {e}")
            st.stop()

    with st.spinner("3단계: 담임교사용 지도방침 생성 중..."):
        try:
            p3 = build_stage3_homeroom_prompt(report_md, summary_md)
            homeroom_md = gemini_generate_text_with_retry(MODEL_GUIDE, p3, None)
            homeroom_md = trim_korean_text_safely(homeroom_md, max_utf8_bytes=9000)
            homeroom_md = sanitize_numbered_lists(homeroom_md)
        except Exception as e:
            st.error(f"3단계 실패: {e}")
            st.stop()

    report_title, guide_title = make_doc_titles(student_num5, student_name.strip())

    placeholders_report = {
        "{{REPORT_CONTENT}}": "컨설팅 보고서(원문)",
        "{{REPORT_SUMMARY}}": "컨설팅 보고서 요약",
        "{{STUDENT_NAME}}": "학생 이름",
        "{{STUDENT_NUM}}": "학번",
    }

    placeholders_guide = {
        "{{HOMEROOM_GUIDANCE}}": "담임교사용 진학지도 조언",
        "{{REPORT_SUMMARY}}": "학생 컨설팅 보고서 요약본",  # ✅ 추가
        "{{STUDENT_NAME}}": "학생 이름",
        "{{STUDENT_NUM}}": "학번",
        "{{NOTES_BLOCK}}": "담임 추가 기재사항",
    }

    with st.spinner("Google Docs 생성/치환 + 자동 서식 적용 중..."):
        try:
            # 문서 1: 보고서
            report_doc_id = copy_template(
                drive_service,
                TEMPLATE_REPORT_DOC_ID,
                report_title,
                DRIVE_FOLDER_ID_REPORT,
            )
            ensure_placeholders_exist(docs_service, report_doc_id, placeholders_report)
            batch_replace_all_text(
                docs_service,
                report_doc_id,
                {
                    "{{STUDENT_NAME}}": student_name.strip(),
                    "{{STUDENT_NUM}}": student_num5,
                    "{{REPORT_CONTENT}}": report_md.strip(),
                    "{{REPORT_SUMMARY}}": summary_md.strip(),
                },
            )
            if auto_gas_format:
                call_gas_auto_format(report_doc_id)
            remove_debug_tokens_after_format(docs_service, report_doc_id)
            report_doc_url = f"https://docs.google.com/document/d/{report_doc_id}/edit"

            # 문서 2: 지도방침
            guide_doc_id = copy_template(
                drive_service, TEMPLATE_GUIDE_DOC_ID, guide_title, DRIVE_FOLDER_ID_GUIDE
            )
            ensure_placeholders_exist(docs_service, guide_doc_id, placeholders_guide)
            batch_replace_all_text(
                docs_service,
                guide_doc_id,
                {
                    "{{STUDENT_NAME}}": student_name.strip(),
                    "{{STUDENT_NUM}}": student_num5,
                    "{{NOTES_BLOCK}}": notes.strip(),
                    "{{REPORT_SUMMARY}}": summary_md.strip(),
                    "{{HOMEROOM_GUIDANCE}}": homeroom_md.strip(),
                },
            )
            if auto_gas_format:
                call_gas_auto_format(guide_doc_id)
            remove_debug_tokens_after_format(docs_service, guide_doc_id)
            guide_doc_url = f"https://docs.google.com/document/d/{guide_doc_id}/edit"

            # Sheets 기록: A:H 정확 매핑 + 하이퍼링크 문구 통일
            report_link = make_hyperlink_formula(report_doc_url, "컨설팅 보고서")
            guide_link = make_hyperlink_formula(guide_doc_url, "조언")

            write_row_to_sheet_from_A6(
                sheets_service,
                [
                    grade,  # A 학년
                    klass,  # B 반
                    number,  # C 번호
                    student_num5,  # D 학번
                    student_name.strip(),  # E 이름
                    report_link,  # F 컨설팅보고서(링크)
                    guide_link,  # G 담임선생님 조언(링크)
                    # H 생성시간은 함수에서 자동
                ],
            )

        except HttpError as e:
            st.error(f"Google API 오류: {e}")
            st.stop()
        except Exception as e:
            st.error(f"문서 생성 실패: {e}")
            st.stop()

    st.success(
        "완료! (보고서/지도방침) 2개 문서 생성 + (선택)자동 서식 + 시트 기록까지 처리했습니다."
    )
    st.link_button("📎 컨설팅 보고서 열기", report_doc_url)
    st.link_button("📎 담임교사 지도방침 열기", guide_doc_url)

    with st.expander("✅ 1단계 보고서(원문)"):
        st.markdown(report_md)
    with st.expander("✅ 2단계 요약"):
        st.markdown(summary_md)
    with st.expander("✅ 3단계 담임 지도방침"):
        st.markdown(homeroom_md)
    with st.expander("✅ 3단계 담임 지도방침"):
        st.markdown(homeroom_md)
        st.markdown(homeroom_md)
