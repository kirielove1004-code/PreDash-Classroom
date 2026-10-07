"""Optional KRX daily market activity with a resilient read-only cache fallback."""
import csv
import io
import re
from datetime import date,timedelta
import requests

class KRXError(ValueError):
    pass

def _as_int(value, default=0):
    try:
        if value is None:return default
        text=str(value).replace(',','').strip()
        if not text or text=='-':return default
        return int(float(text))
    except (TypeError,ValueError):
        return default

def _cached_daily_activity(code,asof):
    """Read the latest KRX daily listing cache without requiring an OPEN API key.

    FinanceDataReader publishes a daily KRX listing cache on GitHub. We try recent
    calendar days and skip holidays/empty market rows.
    """
    base='https://raw.githubusercontent.com/FinanceData/fdr_krx_data_cache/refs/heads/master/data/listing/krx'
    last_error=None
    for offset in range(14):
        day=asof-timedelta(days=offset)
        if day.weekday()>=5:
            continue
        url=f"{base}/{day.isoformat()}.csv"
        try:
            r=requests.get(url,timeout=(5,15),headers={'User-Agent':'PreDash-Classroom/1.0'})
            if r.status_code==404:
                continue
            r.raise_for_status()
            text=r.text.lstrip('\ufeff')
            reader=csv.DictReader(io.StringIO(text))
            for row in reader:
                row_code=str(row.get('Code','')).strip().zfill(6)
                if row_code!=code:
                    continue
                close=_as_int(row.get('Close'))
                volume=_as_int(row.get('Volume'))
                turnover=_as_int(row.get('Amount'))
                cap=_as_int(row.get('Marcap'))
                # Holiday/cache placeholder files can contain "-" and zero market data.
                if close<=0 or (volume<=0 and turnover<=0 and cap<=0):
                    break
                market_raw=str(row.get('Market') or row.get('MarketId') or '').upper()
                market='코스피' if ('KOSPI' in market_raw or market_raw=='STK') else '코스닥' if ('KOSDAQ' in market_raw or market_raw=='KSQ') else market_raw or 'KRX'
                return {
                    'date':day.isoformat(),'volume':volume,'turnover':turnover,'market_cap':cap,
                    'market':market,'source':'KRX 일별 캐시 · FinanceDataReader','fallback':True
                }
        except requests.RequestException as exc:
            last_error=exc
            continue
        except (csv.Error,UnicodeError) as exc:
            last_error=exc
            continue
    raise KRXError('KRX 보조 일별 캐시에서도 최근 거래일 자료를 찾지 못했습니다.') from last_error

def daily_activity(key,code,asof=None):
    """Latest validated KOSPI/KOSDAQ daily record.

    KRX OPEN API is preferred. If its key is rejected or the endpoint is unavailable,
    the dashboard falls back to the public daily KRX cache so watchlists keep working.
    """
    if not re.fullmatch(r'[0-9]{6}',str(code or '')):
        raise KRXError('종목코드를 확인하세요.')
    asof=asof or date.today()
    official_error=None
    rejected_apis=set()
    if key:
        for offset in range(6):
            day=asof-timedelta(days=offset)
            if day.weekday()>=5:continue
            for api in ('stk_bydd_trd','ksq_bydd_trd'):
                if api in rejected_apis:continue
                try:
                    response=requests.get(f'https://data-dbg.krx.co.kr/svc/apis/sto/{api}',
                        headers={'AUTH_KEY':key},params={'basDd':day.strftime('%Y%m%d')},timeout=(5,12))
                    if response.status_code in (401,403):
                        official_error=f'KRX OPEN API HTTP {response.status_code}'
                        rejected_apis.add(api)
                        continue
                    response.raise_for_status()
                    rows=response.json().get('OutBlock_1')
                    if not isinstance(rows,list):
                        official_error='KRX OPEN API 응답 형식 오류'
                        continue
                except (requests.RequestException,ValueError) as exc:
                    official_error=str(exc) or exc.__class__.__name__
                    continue
                for row in rows:
                    if str(row.get('ISU_SRT_CD','')).zfill(6)!=code or str(row.get('BAS_DD',''))!=day.strftime('%Y%m%d'):
                        continue
                    try:
                        volume=int(str(row['ACC_TRDVOL']).replace(',',''))
                        turnover=int(str(row['ACC_TRDVAL']).replace(',',''))
                        cap=int(str(row['MKTCAP']).replace(',',''))
                        if min(volume,turnover,cap)<0:raise ValueError
                    except (KeyError,ValueError,TypeError):
                        official_error='KRX 거래량·거래대금·시가총액 응답 형식 오류'
                        continue
                    return {'date':day.isoformat(),'volume':volume,'turnover':turnover,'market_cap':cap,
                            'market':'코스피' if api=='stk_bydd_trd' else '코스닥',
                            'source':'KRX OPEN API','fallback':False}
            if len(rejected_apis)==2:
                break
    try:
        result=_cached_daily_activity(code,asof)
        if official_error:result['official_error']=official_error
        return result
    except KRXError as exc:
        if official_error:
            raise KRXError(f'{official_error} · {exc}') from exc
        raise


KRX_SERVICES = (
    ('유가증권 일별매매정보','stk_bydd_trd'),
    ('코스닥 일별매매정보','ksq_bydd_trd'),
    ('유가증권 종목기본정보','stk_isu_base_info'),
    ('코스닥 종목기본정보','ksq_isu_base_info'),
)


def diagnose_krx(key,asof):
    """Check each permission separately; HTTP 401 alone does not prove an invalid key."""
    day=asof-timedelta(days=1)
    while day.weekday()>=5:day-=timedelta(days=1)
    checks=[]
    for label,endpoint in KRX_SERVICES:
        item={'service':label,'status':'응답 확인 필요','http':None,'date':day.isoformat()}
        try:
            r=requests.get(f'https://data-dbg.krx.co.kr/svc/apis/sto/{endpoint}',
                headers={'AUTH_KEY':str(key).strip()},params={'basDd':day.strftime('%Y%m%d')},timeout=(5,15))
            item['http']=r.status_code
            if r.status_code in (401,403):
                item['status']='인증·이용승인 확인 필요'
            elif r.status_code==429:item['status']='호출 한도'
            elif r.status_code>=500:item['status']='기관 서버 오류'
            elif r.status_code==404:item['status']='호출 주소 확인 필요'
            elif r.status_code==200:
                try:rows=r.json().get('OutBlock_1')
                except (ValueError,AttributeError):rows=None
                if isinstance(rows,list):
                    item['status']='정상' if rows else '정상 · 해당 날짜 자료 없음'
        except requests.Timeout:item['status']='응답 지연'
        except requests.RequestException:item['status']='연결 실패'
        checks.append(item)
    good=[c for c in checks if c['status'].startswith('정상')]
    evidence=' · '.join(f"{c['service']}: HTTP {c['http']} / {c['status']}" if c['http'] else
                       f"{c['service']}: {c['status']}" for c in checks)
    action=('KRX 마이페이지에서 인증키 승인·활성·사용기간을 확인하고, 서비스 이용 → 주식에서 '
            '유가증권/코스닥 일별매매정보 및 사용하는 종목기본정보의 이용승인을 각각 확인하세요. '
            '샘플 테스트에서도 거부되면 KRX 계정 설정을 먼저 확인하세요.')
    if len(good)==len(checks):
        return {'status':'정상','detail':'KRX 4개 주식 API가 모두 정상 응답했습니다. 휴장일에는 자료가 비어 있을 수 있습니다.',
                'action':'','evidence':evidence,'services':checks}
    if good:
        return {'status':'부분 정상','detail':f'KRX {len(good)}/4개 API가 응답했습니다. 승인된 서비스는 계속 사용합니다. 나머지는 개별 상태를 확인하세요.',
                'action':action,'evidence':evidence,'services':checks}
    denied=[c for c in checks if c['http'] in (401,403)]
    if denied:
        detail=('KRX가 인증 또는 서비스 접근을 거부했습니다. HTTP 401/403만으로 인증키 오류·미승인·만료 원인을 확정할 수 없습니다.')
        status='인증 확인 필요'
    else:
        detail='KRX 직접 연결을 확인하지 못했습니다. 서비스별 응답 상태를 확인하세요.'
        status='응답 지연' if all(c['status']=='응답 지연' for c in checks) else '연결 확인 필요'
    try:
        fallback=daily_activity('', '005930', asof)
        if fallback and fallback.get('date'):
            return {'status':'대체 사용 중','detail':detail+' 거래량·거래대금·시가총액은 공개 일별 캐시로 조회 가능합니다. KRX 직접 인증이 복구된 것은 아닙니다.',
                    'action':action,'evidence':evidence+' · 보조 조회 성공 '+str(fallback['date']),
                    'services':checks,'fallback_date':fallback['date']}
    except KRXError:pass
    return {'status':status,'detail':detail,'action':action,'evidence':evidence,'services':checks}
