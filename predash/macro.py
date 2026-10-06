"""Dated volatility context and descriptive relative price performance."""
import csv,io
from datetime import datetime
from math import isfinite
import requests
class MacroError(ValueError):pass
VIX_URL='https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
def parse_vix(text,today):
    points={}
    try:
        for row in csv.DictReader(io.StringIO(text.lstrip('\ufeff'))):
            day=datetime.strptime(row['DATE'],'%m/%d/%Y').date();value=float(row['CLOSE'])
            if day>today:continue
            if not isfinite(value) or value<=0:raise ValueError
            if day in points and points[day]!=value:raise ValueError
            points[day]=value
    except (KeyError,ValueError,TypeError):raise MacroError('VIX 날짜·종가 응답 확인 실패') from None
    days=sorted(points)
    if len(days)<2 or (today-days[-1]).days>5:raise MacroError('VIX 최근 종가 부족 또는 기준일 경과')
    value=points[days[-1]]
    level='낮음' if value<15 else '보통' if value<20 else '주의' if value<30 else '높음'
    return {'date':days[-1].isoformat(),'close':value,'change':value-points[days[-2]],'level':level,
            'rows':[{'날짜':d.isoformat(),'VIX':points[d]} for d in days[-60:]]}
def fetch_vix(today):
    try:
        response=requests.get(VIX_URL,timeout=(5,15));response.raise_for_status()
        if len(response.content)>5_000_000:raise MacroError('VIX 응답 크기 초과')
        return parse_vix(response.text,today)
    except requests.RequestException:raise MacroError('Cboe VIX 공식 자료 조회 실패 · 잠시 후 다시 조회하세요.') from None

def relative(stock,index,code,today):
    def series(rows,dk,vk,stock_only=False):
        values={}
        for r in rows:
            if stock_only and str(r.get('srtnCd','')).removeprefix('A').zfill(6)!=code:continue
            try:
                day=datetime.strptime(str(r[dk]),'%Y%m%d').date();v=float(str(r[vk]).replace(',',''))
                if day>today or not isfinite(v) or v<=0:raise ValueError
            except (KeyError,ValueError,TypeError):raise MacroError('상대성과 날짜·가격 확인 실패') from None
            if day in values and values[day]!=v:raise MacroError('상대성과 중복 가격 충돌')
            values[day]=v
        return values
    s=series(stock,'basDt','clpr',True);m=series(index,'stck_bsop_date','bstp_nmix_prpr');days=sorted(m)
    if not days or (today-days[-1]).days>5:raise MacroError('비교 지수 기준일 경과')
    end=days[-1];result=[]
    for n in (1,5,20):
        row={'sessions':n,'date':end.isoformat(),'stock_pct':None,'market_pct':None,'multiple':None,'excess_pp':None,'status':'자료 부족'}
        if len(days)>n:
            start=days[-n-1];row['from']=start.isoformat()
            if all(d in s for d in days[-n-1:]):
                sr=(s[end]/s[start]-1)*100;mr=(m[end]/m[start]-1)*100
                row.update(stock_pct=sr,market_pct=mr,excess_pp=sr-mr)
                if abs(mr)<0.1:row['status']='지수 보합 · 배수 보류'
                elif mr>0:
                    ratio=sr/mr;row['multiple']=ratio
                    row['status']='매우 우수' if ratio>=3-1e-9 else '양호' if ratio>1+1e-9 else '소외'
                else:
                    row['status']='하락장 상대 강세' if sr>mr+1e-9 else '하락장 상대 약세' if sr<mr-1e-9 else '지수 수준 하락'
                    row['downside_multiple']=sr/mr
        result.append(row)
    return result

def benchmark(rows,code):
    markets={str(r.get('mrktCtg','')).upper() for r in rows if str(r.get('srtnCd','')).removeprefix('A').zfill(6)==code}
    if markets=={'KOSPI'}:return '코스피'
    if markets=={'KOSDAQ'}:return '코스닥'
    return None



def public_index_bars(code,today):
    """Read-only KOSPI/KOSDAQ index fallback via FinanceDataReader."""
    symbol='KS11' if code=='0001' else 'KQ11' if code=='1001' else None
    if not symbol:
        raise MacroError('지원하지 않는 지수입니다.')
    try:
        import FinanceDataReader as fdr
        from datetime import timedelta
        frame=fdr.DataReader(symbol,(today-timedelta(days=70)).isoformat(),(today+timedelta(days=1)).isoformat())
    except Exception as exc:
        raise MacroError('시장 지수 보조조회에 실패했습니다.') from exc
    if frame is None or frame.empty:
        raise MacroError('시장 지수 보조자료가 없습니다.')
    rows=[]
    for idx,row in frame.iterrows():
        try:
            close=float(row['Close'])
            if close<=0:continue
            rows.append({'stck_bsop_date':idx.strftime('%Y%m%d'),'bstp_nmix_prpr':close})
        except Exception:
            continue
    if not rows:
        raise MacroError('시장 지수 보조자료를 읽지 못했습니다.')
    return rows
