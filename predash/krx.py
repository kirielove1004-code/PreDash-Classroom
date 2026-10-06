"""Optional KRX daily market activity with a resilient read-only fallback."""
import re
from datetime import date,timedelta
import requests

class KRXError(ValueError):
    pass

def _as_int(value, default=0):
    try:
        if value is None:return default
        text=str(value).replace(',','').strip()
        if not text:return default
        return int(float(text))
    except (TypeError,ValueError):
        return default

def _fdr_daily_activity(code,asof):
    """Fallback to FinanceDataReader's KRX reader when OPEN API auth is unavailable."""
    try:
        import FinanceDataReader as fdr
        start=(asof-timedelta(days=14)).isoformat()
        end=(asof+timedelta(days=1)).isoformat()
        frame=fdr.DataReader('KRX:'+code,start,end)
        if frame is None or frame.empty:
            raise ValueError('empty KRX frame')
        frame=frame[frame.index.date<=asof]
        if frame.empty:
            raise ValueError('no row before asof')
        row=frame.iloc[-1]
        idx=frame.index[-1]
        volume=_as_int(row.get('Volume'))
        turnover=_as_int(row.get('Amount'))
        cap=_as_int(row.get('MarCap'))
        market=''
        try:
            listing=fdr.StockListing('KRX')
            if listing is not None and not listing.empty:
                code_col='Code' if 'Code' in listing.columns else 'Symbol' if 'Symbol' in listing.columns else None
                if code_col:
                    hit=listing[listing[code_col].astype(str).str.zfill(6)==code]
                    if not hit.empty:
                        raw=str(hit.iloc[0].get('Market') or '').upper()
                        market='코스피' if 'KOSPI' in raw else '코스닥' if 'KOSDAQ' in raw else raw
        except Exception:
            market=''
        return {
            'date':idx.date().isoformat(),'volume':volume,'turnover':turnover,'market_cap':cap,
            'market':market or 'KRX','source':'FinanceDataReader · KRX 원천 보조조회','fallback':True
        }
    except Exception as exc:
        raise KRXError('KRX 보조 시세 조회에도 실패했습니다.') from exc

def daily_activity(key,code,asof=None):
    """Latest validated KOSPI/KOSDAQ daily record.

    KRX OPEN API is preferred when an authorized key is available. If the key is
    missing/rejected or the API is temporarily unavailable, a read-only KRX data
    fallback keeps the dashboard usable.
    """
    if not re.fullmatch(r'[0-9]{6}',str(code or '')):
        raise KRXError('종목코드를 확인하세요.')
    asof=asof or date.today()
    official_error=None
    if key:
        for offset in range(6):
            day=asof-timedelta(days=offset)
            if day.weekday()>=5:continue
            for api in ('stk_bydd_trd','ksq_bydd_trd'):
                try:
                    response=requests.get(f'https://data-dbg.krx.co.kr/svc/apis/sto/{api}',
                        headers={'AUTH_KEY':key},params={'basDd':day.strftime('%Y%m%d')},timeout=(5,12))
                    if response.status_code in (401,403):
                        official_error=f'KRX OPEN API HTTP {response.status_code}'
                        break
                    response.raise_for_status()
                    rows=response.json().get('OutBlock_1')
                    if not isinstance(rows,list):
                        raise KRXError('KRX 응답 형식을 확인하지 못했습니다.')
                except (requests.RequestException,ValueError,KRXError) as exc:
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
            if official_error and ('401' in official_error or '403' in official_error):
                break
    try:
        result=_fdr_daily_activity(code,asof)
        if official_error:result['official_error']=official_error
        return result
    except KRXError as exc:
        if official_error:
            raise KRXError(f'{official_error} · {exc}') from exc
        raise
