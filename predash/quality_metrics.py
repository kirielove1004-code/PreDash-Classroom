"""Evidence-first metrics for semiconductor materials/equipment candidates.

Never turn missing fiscal data or a partial trading window into a zero.
All amounts from DART are KRW, including cumulative cash flow.
"""
import os
import re
from datetime import date, timedelta
from predash.official import Official, DataError

TARGETS = {"074600": "원익QnC", "101490": "에스앤에스텍", "319660": "피에스케이"}
FLOW_NAMES = ("외국인합계", "기관합계")
CF_OPERATING = ("ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities")
CAPEX_TANGIBLE = ("ifrs-full_PurchaseOfPropertyPlantAndEquipment", "ifrs_PurchaseOfPropertyPlantAndEquipment")
CAPEX_INTANGIBLE = ("ifrs-full_PurchaseOfIntangibleAssets", "ifrs_PurchaseOfIntangibleAssets")


def _value(item):
    try:
        value = str(item).replace(",", "").strip()
        return int(value) if value not in ("", "-", "None") else None
    except (TypeError, ValueError):
        return None


def _lookup(rows, ids, keywords=()):
    for row in rows:
        if row.get("account_id") in ids and row.get("fs_div") == "CFS":
            n = _value(row.get("thstrm_amount"))
            if n is not None:
                return n
    for row in rows:
        name = re.sub(r"\\s+", "", str(row.get("account_nm") or ""))
        if row.get("fs_div") == "CFS" and any(x in name for x in keywords):
            n = _value(row.get("thstrm_amount"))
            if n is not None:
                return n
    return None


def _cashflow_period(client, corp, year, report_code):
    payload = client.dart("fnlttSinglAcntAll.json", corp_code=corp, bsns_year=str(year),
                          reprt_code=report_code, fs_div="CFS")
    if not payload or not payload.get("list"):
        return None, "해당 기간 연결 현금흐름표 없음"
    rows = payload["list"]
    operating = _lookup(rows, CF_OPERATING, ("영업활동현금흐름", "영업활동으로인한현금흐름"))
    tangible = _lookup(rows, CAPEX_TANGIBLE, ("유형자산의취득", "유형자산취득"))
    intangible = _lookup(rows, CAPEX_INTANGIBLE, ("무형자산의취득", "무형자산취득"))
    if None in (operating, tangible, intangible):
        return None, "영업현금흐름 또는 유형·무형자산 취득액 식별 불가"
    capex = abs(tangible) + abs(intangible)
    return {"ocf":operating,"tangible":abs(tangible),"intangible":abs(intangible),
            "capex":capex,"fcf":operating-capex}, None


def _ttm(client, corp, today):
    # The latest publicly available interim report, not the current calendar quarter.
    y = today.year
    choices = ((y,"11014",9), (y,"11012",6), (y,"11013",3),
               (y-1,"11011",12), (y-1,"11014",9), (y-1,"11012",6), (y-1,"11013",3))
    for year, report, month in choices:
        current, issue = _cashflow_period(client, corp, year, report)
        if current is None:
            continue
        if report == "11011":
            return current, {"mode":"FY","year":year,"months":12,"formula":"연간 FCF"}, None
        prev_fy, _ = _cashflow_period(client, corp, year-1, "11011")
        prev_same, _ = _cashflow_period(client, corp, year-1, report)
        if prev_fy is None or prev_same is None:
            return None, None, "TTM에 필요한 전년도 연간·동기간 현금흐름표 부족"
        return {k:prev_fy[k]+current[k]-prev_same[k] for k in current}, {
            "mode":"TTM","year":year,"months":month,
            "formula":"전년도 연간 + 금년 누적 - 전년도 동기간 누적"}, None
    return None, None, "최근 연결 현금흐름표 조회 실패"


def _flow(code, today):
    try:
        from pykrx import stock
        start=(today-timedelta(days=75)).strftime("%Y%m%d")
        frame=stock.get_market_trading_volume_by_date(start,today.strftime("%Y%m%d"),
                       code,on="순매수",detail=False,freq="d")
        if frame is None or frame.empty:
            return None, "KRX 수급 데이터 없음"
        frame=frame.sort_index()
        for key in FLOW_NAMES:
            if key not in frame.columns:
                return None, key+" 항목 없음"
        frame=frame.dropna(subset=list(FLOW_NAMES))
        frame=frame[frame.index.date <= today]
        if len(frame)<20:
            return None, f"확인된 거래일 {len(frame)}일: 20일 합산 금지"
        selected=frame.tail(20)
        if selected.index[-1].date() < today-timedelta(days=5):
            return None, "최근 수급 데이터가 오래됨"
        return {"start":str(selected.index[0].date()),"end":str(selected.index[-1].date()),
                "sessions":20,"foreign_shares":int(selected[FLOW_NAMES[0]].sum()),
                "institution_shares":int(selected[FLOW_NAMES[1]].sum()),
                "source":"KRX 공개자료(pykrx), 20거래일 순매수 수량"}, None
    except Exception as exc:
        return None, "KRX 수급 수집 실패: "+str(exc)[:120]


def inspect(code, today=None):
    today=today or date.today()
    result={"code":code,"name":TARGETS.get(code,code),"as_of":today.isoformat(),
            "ttm_fcf":None,"fcf_yield":None,"roic":None,"flow_20d":None,"issues":[]}
    client=Official()
    if not client.dart_key:
        result["issues"].append("DART_CRTFC_KEY 미설정")
    else:
        try:
            corp=client.corp(code)
            fcf, period, issue=_ttm(client,corp,today)
            if issue: result["issues"].append("FCF: "+issue)
            else:
                result["ttm_fcf"]={**fcf,"period":period,"basis":"CFS","currency":"KRW"}
                # Only compute yield using market cap from the exact last available trading day.
                try:
                    from predash.krx import daily_activity
                    market=daily_activity(os.getenv("KRX_AUTH_KEY",""),code,today)
                    cap=market.get("market_cap")
                    if cap and cap>0:
                        result["fcf_yield"]={"value_pct":round(100*fcf["fcf"]/cap,2),
                                             "market_cap":cap,"price_date":market["date"],
                                             "source":market.get("source")}
                    else: result["issues"].append("FCF Yield: 시가총액 없음")
                except Exception as exc:
                    result["issues"].append("FCF Yield: 시총 조회 실패 ("+str(exc)[:90]+")")
        except (DataError, ValueError) as exc:
            result["issues"].append("FCF: "+str(exc)[:140])
    # ROIC is NOT fabricated from ROE, operating margin or incomplete balance-sheet fields.
    result["roic"]={"value_pct":None,"status":"미평가",
                    "reason":"NOPAT 및 기초·기말 투하자본(영업자산·무이자부채) 일관된 추출·검증 필요"}
    flow, issue=_flow(code,today)
    if issue: result["issues"].append("수급: "+issue)
    else: result["flow_20d"]=flow
    return result


def inspect_all(today=None):
    return {"as_of":str(today or date.today()),"stocks":[inspect(c,today) for c in TARGETS]}
