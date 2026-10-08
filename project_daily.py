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



def _rules_token():
    import streamlit as st
    try:
        return str(st.secrets.get("GITHUB_RULES_TOKEN", "")).strip()
    except (FileNotFoundError, KeyError):
        return os.getenv("GITHUB_RULES_TOKEN", "").strip()


def _save_rules(new_cfg):
    """Persist to the GitHub repository, not ephemeral Streamlit disk."""
    import base64
    import requests
    token = _rules_token()
    if not token:
        raise RuntimeError("Streamlit Secrets에 GITHUB_RULES_TOKEN을 먼저 설정해야 영구 저장할 수 있습니다.")
    repo = "kirielove1004-code/PreDash-Classroom"
    url = f"https://api.github.com/repos/{repo}/contents/project_daily_config.json"
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    existing = requests.get(url, headers=headers, timeout=20)
    existing.raise_for_status()
    sha = existing.json()["sha"]
    payload = {"message": "config: update project-specific investment guidelines",
               "sha": sha, "branch": "main",
               "content": base64.b64encode((json.dumps(new_cfg, ensure_ascii=False, indent=2) + "\n").encode()).decode()}
    response = requests.put(url, headers=headers, json=payload, timeout=25)
    if response.status_code == 409:
        raise RuntimeError("다른 수정과 충돌했습니다. 화면을 새로고침하고 다시 저장하세요.")
    response.raise_for_status()
    return response.json().get("commit", {}).get("sha")


def _parse_stock_codes(text):
    parts = re.split(r"[,\s;]+", text.strip())
    codes = valid_codes(parts)
    invalid = [x for x in parts if x and not re.fullmatch(r"\d{6}", x)]
    if invalid:
        raise ValueError("종목코드는 6자리 숫자를 쉼표로 구분해 입력하세요.")
    return codes


def render_rule_manager(cfg, browser_codes):
    import streamlit as st
    st.subheader("내 분석 지침 관리")
    st.caption("각 지침의 이름·원문·분석할 종목을 각각 등록합니다. 장중이 아닌 평일 자동 수집 결과를 지침별로 구분합니다.")
    st.info("분석 지침 원문은 ChatGPT 프로젝트와 자동 동기화되지 않습니다. 이 화면에 직접 붙여 넣으세요.")
    authorized = bool(_rules_token())
    if not authorized:
        st.warning("현재 읽기 전용입니다. 영구 저장하려면 Streamlit Secrets에 저장소 Contents 권한으로 제한한 GITHUB_RULES_TOKEN을 추가해야 합니다. 토큰을 이 화면에 붙여 넣지 마세요.")
    projects = cfg.get("projects", [])
    names = ["+ 새 지침"] + [p.get("name", "이름 없음") for p in projects]
    chosen = st.selectbox("등록하거나 편집할 지침", names, key="guideline_editor_pick")
    position = names.index(chosen) - 1
    existing = projects[position] if position >= 0 else {}
    with st.form("guideline_editor"):
        name = st.text_input("지침 이름", value=existing.get("name", ""), max_chars=80,
                             placeholder="예: 기술 희소성 · 고수익 성장주")
        instruction = st.text_area("분석 지침 원문", value=existing.get("instructions", ""),
                                   height=220, placeholder="판단 기준, 우선순위, 근거 자료, 제외 조건 등을 자유롭게 입력하세요.")
        stock_codes = st.text_area("대상 종목코드 (6자리, 쉼표 구분)",
                                   value=", ".join(valid_codes(existing.get("stocks", []))),
                                   placeholder="005380, 267260", height=85)
        threshold_text = st.text_input("최소 영업이익률 (%) · 선택 사항",
                                       value="" if existing.get("minimum_operating_margin_pct") is None else str(existing["minimum_operating_margin_pct"]),
                                       placeholder="예: 15")
        submitted = st.form_submit_button("지침 영구 저장", disabled=not authorized, type="primary")
    if submitted:
        try:
            codes = _parse_stock_codes(stock_codes)
            if not name.strip() or not instruction.strip() or not codes:
                raise ValueError("지침 이름, 지침 원문, 종목코드를 모두 입력하세요.")
            threshold = float(threshold_text) if threshold_text.strip() else None
            if threshold is not None and not -100 <= threshold <= 100:
                raise ValueError("영업이익률 기준을 -100~100 사이로 입력하세요.")
            edited = dict(cfg)
            edited["projects"] = [dict(p) for p in projects]
            entry = {"name": name.strip(), "instructions": instruction.strip(),
                     "stocks": [{"code": c} for c in codes],
                     "minimum_operating_margin_pct": threshold,
                     "instructions_verified": True}
            if position == -1:
                if any(p.get("name") == entry["name"] for p in projects):
                    raise ValueError("동일한 이름의 지침이 이미 있습니다.")
                edited["projects"].append(entry)
            else:
                if any(i != position and p.get("name") == entry["name"] for i, p in enumerate(projects)):
                    raise ValueError("동일한 이름의 지침이 이미 있습니다.")
                edited["projects"][position] = entry
            _save_rules(edited)
            st.success("GitHub에 저장했습니다. 다음 자동 수집부터 대상에 포함됩니다.")
            st.rerun()
        except (ValueError, RuntimeError, Exception) as exc:
            st.error("저장 실패: " + str(exc)[:220])
    if position >= 0 and authorized:
        if st.checkbox("이 지침을 삭제하겠습니다", key="confirm_guideline_delete"):
            if st.button("선택 지침 삭제", type="secondary"):
                try:
                    edited = dict(cfg)
                    edited["projects"] = [p for i, p in enumerate(projects) if i != position]
                    _save_rules(edited)
                    st.success("지침을 삭제했습니다.")
                    st.rerun()
                except Exception as exc:
                    st.error("삭제 실패: " + str(exc)[:220])
    st.divider()
    st.subheader("관심종목 자동 갱신 등록")
    browser = valid_codes(browser_codes or [])
    st.caption("브라우저 관심종목은 서버 예약 작업에서 읽을 수 없습니다. 아래에 등록된 종목만 무인 갱신됩니다.")
    default = valid_codes(cfg.get("watchlist_codes", []))
    selected = st.text_area("매일 수집할 관심종목 (6자리)", value=", ".join(default),
                             key="server_watchlist_codes")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("현재 브라우저 관심종목 추가", disabled=not bool(browser)):
            st.session_state.server_watchlist_codes = ", ".join(dict.fromkeys(default + browser))
            st.rerun()
    with c2:
        if st.button("관심종목 영구 저장", disabled=not authorized):
            try:
                edited = dict(cfg)
                edited["watchlist_codes"] = _parse_stock_codes(st.session_state.server_watchlist_codes)
                _save_rules(edited)
                st.success("관심종목이 GitHub에 저장되었습니다.")
                st.rerun()
            except Exception as exc:
                st.error("저장 실패: " + str(exc)[:220])
    st.caption("프로젝트 지침 원문은 GitHub 저장소에 저장됩니다. 민감한 개인정보, API 키 또는 비공개 배포권이 없는 자료는 입력하지 마세요.")

def render(browser_codes=None):
    import streamlit as st
    st.title("지침 종목 · 일일 분석")
    st.caption("공식 종가와 OpenDART 최근 결산 정보 · 자동 매수 추천 아님")
    cfg = config()
    view, manage = st.tabs(["일일 분석 결과", "지침 등록 · 편집"])
    with manage:
        render_rule_manager(cfg, browser_codes)
    with view:
        _render_daily_results(cfg, browser_codes)


def _render_daily_results(cfg, browser_codes):
    import streamlit as st
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
    if selected_project and selected_project.get("instructions"):
        with st.expander("등록된 지침 확인"):
            st.text(selected_project["instructions"])
    rows = []
    for code in groups[selected]:
        raw = rows_by_code.get(code, {})
        financial = raw.get("financial") or {}
        price = raw.get("price") or {}
        issues = raw.get("issues", [])
        rows.append({"종목명": raw.get("name") or code, "종목코드": code,
                     "최근 종가": price.get("close"), "종가 기준일": price.get("as_of"),
                     "최근 결산연도": financial.get("year"), "영업이익률(%)": financial.get("operating_margin"),
                     "지침 판정": ("정량 조건 미충족" if selected_project and selected_project.get("instructions_verified") and selected_project.get("minimum_operating_margin_pct") is not None and financial.get("operating_margin") is not None and financial.get("operating_margin") < selected_project["minimum_operating_margin_pct"] else "정량 충족 · 정성 검토 필요" if selected_project and selected_project.get("instructions_verified") and selected_project.get("minimum_operating_margin_pct") is not None and financial.get("operating_margin") is not None else "지침 해석 대기"),
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
