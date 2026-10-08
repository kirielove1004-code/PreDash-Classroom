"""Official-data daily project and saved-watchlist screening.
No model-generated ratings; stale/unavailable facts remain explicitly unverified.
"""
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "project_daily_config.json"
SNAPSHOT = ROOT / "data" / "project_daily_latest.json"
KST = ZoneInfo("Asia/Seoul")


def config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def valid_codes(items):
    return list(dict.fromkeys(str(x.get("code") if isinstance(x, dict) else x).strip()
                              for x in items if re.fullmatch(r"\d{6}", str(x.get("code") if isinstance(x, dict) else x).strip())))[:80]


def tracked(cfg):
    codes = valid_codes(cfg.get("watchlist_codes", []))
    for project in cfg.get("projects", []):
        codes.extend(valid_codes(project.get("stocks", [])))
    return list(dict.fromkeys(codes))


def collect():
    from predash.official import Official, DataError
    cfg = config()
    codes = tracked(cfg)
    if not codes:
        raise RuntimeError("등록된 분석 종목이 없습니다. project_daily_config.json을 설정하세요.")
    if not os.getenv("DART_CRTFC_KEY") or not os.getenv("DATA_GO_KR_SERVICE_KEY"):
        raise RuntimeError("GitHub Actions의 DART_CRTFC_KEY / DATA_GO_KR_SERVICE_KEY Secrets가 필요합니다.")
    old = {}
    if SNAPSHOT.exists():
        try:
            old = {str(x["code"]): x for x in json.loads(SNAPSHOT.read_text(encoding="utf-8")).get("stocks", [])}
        except (ValueError, OSError, KeyError, TypeError):
            pass
    client = Official()
    now = datetime.now(KST).isoformat(timespec="seconds")
    result = []
    for code in codes:
        row = dict(old.get(code, {"code": code}))
        row["code"] = code
        row["checked_at"] = now
        row["issues"] = []
        try:
            close, asof, name = client.price(code, date.today())
            row["price"] = {"close": close, "as_of": str(asof)}
            row["name"] = name
        except (DataError, ValueError, TypeError) as exc:
            row["issues"].append("시세: " + str(exc)[:170])
        try:
            report = client.automatic(code)
            years = report.get("years", [])
            latest = years[-1] if years else {}
            revenue = latest.get("revenue")
            profit = latest.get("profit")
            margin = round(100 * profit / revenue, 2) if isinstance(profit, (int,float)) and isinstance(revenue,(int,float)) and revenue > 0 else None
            row["financial"] = {"year": latest.get("year"), "basis": report.get("basis"),
                                "revenue": revenue, "operating_profit": profit, "operating_margin": margin}
            row["financial_checked_at"] = now
        except (DataError, ValueError, TypeError, KeyError) as exc:
            row["issues"].append("실적: " + str(exc)[:170])
        row["last_success"] = now if not row["issues"] else old.get(code, {}).get("last_success")
        result.append(row)
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement: preserve old result if collection fails before completion.
    import tempfile
    import os as _os
    payload = {"checked_at": now, "stocks": result, "count": len(result)}
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=SNAPSHOT.parent, delete=False) as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp = f.name
    _os.replace(tmp, SNAPSHOT)
    print("screened", len(result), "stocks; partial errors", sum(bool(x["issues"]) for x in result))


def render(browser_codes=None):
    import streamlit as st
    st.title("지침 종목 · 일일 분석")
    st.caption("공식 종가와 OpenDART 최근 결산 정보 · 자동 매수 추천 아님")
    cfg = config()
    stored = {}
    if SNAPSHOT.exists():
        try:
            stored = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            st.error("자동 수집 결과 파일을 읽을 수 없습니다.")
    st.caption("마지막 자동 수집: " + str(stored.get("checked_at") or "아직 실행되지 않음") + " (한국시간)")
    watch = valid_codes(cfg.get("watchlist_codes", []))
    browser = valid_codes(browser_codes or [])
    project_codes = {p.get("name", "미분류"): valid_codes(p.get("stocks", [])) for p in cfg.get("projects", [])}
    groups = {"전체": list(dict.fromkeys(watch + browser + [c for codes in project_codes.values() for c in codes])),
              "내 관심종목": list(dict.fromkeys(watch + browser)), **project_codes}
    selected = st.selectbox("분석 그룹", list(groups))
    if not watch:
        st.info("서버에 등록된 관심종목이 없습니다. 앱 관심종목은 현재 접속 시 표시되지만 매일 자동 수집하려면 project_daily_config.json의 watchlist_codes에 등록해야 합니다.")
    if browser:
        st.caption("현재 브라우저의 관심종목 " + ", ".join(browser) + " · 서버에 미등록된 코드는 자동 수집되지 않습니다.")
    rows_by_code = {str(item.get("code")): item for item in stored.get("stocks", [])}
    selected_project = next((p for p in cfg.get("projects", []) if p.get("name") == selected), None)
    if selected_project and not selected_project.get("instructions_verified"):
        st.warning("이 프로젝트의 ChatGPT 지침 원문이 아직 검증 등록되지 않았습니다. 재무정보만 표시하며 지침 충족 판정을 하지 않습니다.")
    rows = []
    for code in groups[selected]:
        raw = rows_by_code.get(code, {})
        financial = raw.get("financial") or {}
        price = raw.get("price") or {}
        issues = raw.get("issues", [])
        rows.append({"종목명": raw.get("name") or code, "종목코드": code,
                     "최근 종가": price.get("close"), "종가 기준일": price.get("as_of"),
                     "최근 결산연도": financial.get("year"), "영업이익률(%)": financial.get("operating_margin"),
                     "지침 판정": "미검증 · 분석 기준 등록 필요",
                     "데이터 상태": "미수집" if not raw else ("일부 조회 실패" if issues else "수집 완료"),
                     "문제": " / ".join(issues)})
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.download_button("분석 결과 JSON 내려받기", json.dumps(rows, ensure_ascii=False, indent=2),
                           file_name="project-daily-analysis.json", mime="application/json")
    else:
        st.info("이 그룹에 등록된 종목이 없습니다.")
    st.caption("수치의 기준일은 서로 다를 수 있습니다. 기술희소성·경쟁사 경쟁력·미래 성장률·적정주가는 근거 없이 자동 산정하지 않습니다.")
    st.caption("수집 실패 시 이전 값은 유지될 수 있으므로 반드시 마지막 수집일·데이터 상태를 확인하세요.")
