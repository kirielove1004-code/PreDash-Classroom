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
    if key:
        for offset in range(6):
            day=asof-timedelta(days=offset)
            if day.weekday()>=5:continue
            rejected=False
            for api in ('stk_bydd_trd','ksq_bydd_trd'):
                try:
                    response=requests.get(f'https://data-dbg.krx.co.kr/svc/apis/sto/{api}',
                        headers={'AUTH_KEY':key},params={'basDd':day.strftime('%Y%m%d')},timeout=(5,12))
                    if response.status_code in (401,403):
                        official_error=f'KRX OPEN API HTTP {response.status_code}'
                        rejected=True
                        break
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
            if rejected:
                break
    try:
        result=_cached_daily_activity(code,asof)
        if official_error:result['official_error']=official_error
        return result
    except KRXError as exc:
        if official_error:
            raise KRXError(f'{official_error} · {exc}') from exc
        raise
