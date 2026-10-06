"""Read-only Kiwoom Securities REST adapter for PreDash Classroom.

Uses only inquiry/quotation TRs. No order endpoints are implemented.
"""
from __future__ import annotations
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import requests

class BrokerError(RuntimeError):
    pass

def number(value, default=None):
    try:
        text=str(value).strip().replace(',','')
        if text=='':
            if default is not None:return default
            raise ValueError
        result=float(text)
        if result!=result or abs(result)==float('inf'):raise ValueError
        return result
    except (TypeError,ValueError):
        if default is not None:return default
        raise BrokerError('키움증권 응답의 숫자를 확인할 수 없습니다.') from None

def clean_price(value):
    """Kiwoom price fields may carry a +/- sign; dashboard needs absolute price."""
    return abs(number(value,0))

class Kiwoom:
    def __init__(self, mode=None, *, settings=None):
        settings=settings or {}
        self.mode=mode or settings.get('mode','real')
        self.key=str(settings.get('key','')).strip()
        self.secret=str(settings.get('secret','')).strip()
        # Kept only for compatibility with old callers; Kiwoom app keys are linked
        # to accounts at the Kiwoom REST portal, so these are not user inputs.
        self.cano=''
        self.product=''
        if not self.key or not self.secret:
            raise BrokerError('키움증권 REST API App Key와 App Secret을 설정하세요.')
        if self.mode not in ('real','demo'):
            raise BrokerError('키움증권 환경은 real 또는 demo여야 합니다.')
        self.base='https://api.kiwoom.com' if self.mode=='real' else 'https://mockapi.kiwoom.com'
        self.token=None
        self.expires=0

    def call(self,method,path,**kwargs):
        try:
            response=requests.request(method,self.base+path,timeout=(5,25),**kwargs)
            if response.status_code in (401,403):
                raise BrokerError(f'키움증권 인증 거부 (HTTP {response.status_code}) · 실전/모의 환경과 App Key·Secret을 확인하세요.')
            if response.status_code==429:
                raise BrokerError('키움증권 호출 제한 (HTTP 429) · 잠시 후 다시 시도하세요.')
            response.raise_for_status()
            data=response.json()
            if not isinstance(data,dict):raise ValueError
            return response,data
        except BrokerError:
            raise
        except (requests.RequestException,ValueError):
            raise BrokerError('키움증권 연결 실패 · 키, 환경, 서비스 상태를 확인하세요.') from None

    @staticmethod
    def _result_error(data,context):
        code=data.get('return_code')
        msg=str(data.get('return_msg','')).strip()
        safe_msg=re.sub(r'[^0-9A-Za-z가-힣 _.,:()\-]','',msg)[:160]
        return BrokerError(f"{context} · 키움 응답 {code}: {safe_msg or '상세 메시지 없음'}")

    def authorize(self):
        if self.token and time.time()<self.expires:return
        _,data=self.call('POST','/oauth2/token',
            headers={'Content-Type':'application/json;charset=UTF-8'},
            json={'grant_type':'client_credentials','appkey':self.key,'secretkey':self.secret})
        token=data.get('token') or data.get('access_token')
        if not token:
            raise self._result_error(data,'키움증권 접근토큰 발급 실패')
        self.token=str(token)
        # Official tokens are valid for 24h. Keep an earlier local refresh margin.
        self.expires=time.time()+23*3600

    def _headers(self,api_id,cont_yn=None,next_key=None):
        self.authorize()
        h={'authorization':'Bearer '+self.token,'Content-Type':'application/json;charset=UTF-8','api-id':api_id}
        if cont_yn:h['cont-yn']=cont_yn
        if next_key:h['next-key']=next_key
        return h

    def _pages(self,api_id,path,body,max_pages=10):
        rows=[]
        cont_yn=next_key=None
        last=None
        delay=1.05 if self.mode=='demo' else 0.22
        for page in range(max_pages):
            response,data=self.call('POST',path,headers=self._headers(api_id,cont_yn,next_key),json=body)
            if data.get('return_code') not in (None,0,'0'):
                raise self._result_error(data,f'{api_id} 조회 실패')
            rows.append(data);last=data
            cont_yn=response.headers.get('cont-yn') or response.headers.get('Cont-Yn')
            next_key=response.headers.get('next-key') or response.headers.get('Next-Key')
            if cont_yn!='Y' or not next_key:break
            if page+1>=max_pages:break
            time.sleep(delay)
        return rows,last or {}

    def balance(self):
        """Domestic-stock evaluation balance (kt00018) plus cash balance (kt00005)."""
        pages,_=self._pages('kt00018','/api/dostk/acnt',{'qry_tp':'1','dmst_stex_tp':'KRX'})
        raw=[]
        summary={}
        for data in pages:
            if not summary:
                summary={k:data.get(k) for k in ('tot_pur_amt','tot_evlt_amt','tot_evlt_pl','prsm_dpst_aset_amt')}
            part=data.get('acnt_evlt_remn_indv_tot') or []
            if isinstance(part,list):raw.extend(x for x in part if isinstance(x,dict))
        positions=[];seen=set()
        for row in raw:
            code=str(row.get('stk_cd','')).strip().replace('A','')
            if not code or code in seen:continue
            qty=number(row.get('rmnd_qty'),0)
            if qty<=0:continue
            seen.add(code)
            price=clean_price(row.get('cur_prc'))
            value=number(row.get('evlt_amt'),price*qty)
            pnl=number(row.get('evltv_prft'),0)
            avg=clean_price(row.get('pur_pric'))
            positions.append({'code':code.zfill(6),'name':str(row.get('stk_nm') or code),
                'quantity':qty,'average_cost':avg,'price':price,'value':value,'pnl':pnl})
        total=number(summary.get('tot_evlt_amt'),sum(p['value'] for p in positions))
        if total<=0:total=sum(p['value'] for p in positions)
        for p in positions:p['weight']=p['value']/total*100 if total>0 else 0
        cash=None
        try:
            _,cash_data=self._pages('kt00005','/api/dostk/acnt',{'dmst_stex_tp':'KRX'},max_pages=1)
            if cash_data.get('entr') not in (None,''):cash=number(cash_data.get('entr'))
        except BrokerError:
            cash=None
        return {'positions':positions,'value':total,'pnl':number(summary.get('tot_evlt_pl'),sum(p['pnl'] for p in positions)),
                'cash':cash,'mode':self.mode,'fetched':datetime.now(ZoneInfo('Asia/Seoul')).isoformat()}

    def investor_flow(self,code):
        """Daily net-buy quantities by individual/foreign/institution (ka10059)."""
        if not re.fullmatch(r'[0-9A-Z]{6}',str(code).upper()):
            raise BrokerError('수급 종목코드를 확인하세요.')
        today=datetime.now(ZoneInfo('Asia/Seoul')).date()
        pages,_=self._pages('ka10059','/api/dostk/stkinfo',
            {'dt':today.strftime('%Y%m%d'),'stk_cd':str(code).upper(),'amt_qty_tp':'2','trde_tp':'0','unit_tp':'1'})
        converted=[]
        for data in pages:
            for row in data.get('stk_invsr_orgn') or []:
                if not isinstance(row,dict):continue
                converted.append({'stck_bsop_date':row.get('dt'),
                    'prsn_ntby_qty':row.get('ind_invsr'),'frgn_ntby_qty':row.get('frgnr_invsr'),
                    'orgn_ntby_qty':row.get('orgn')})
        from predash.flow import summarize_flow
        return summarize_flow(converted,today)

    def fills(self,days=30):
        """Completed domestic orders for recent calendar days, normalized to legacy parser fields."""
        if not isinstance(days,int) or not 1<=days<=90:
            raise BrokerError('조회기간은 1~90일 사이로 선택하세요.')
        end=datetime.now(ZoneInfo('Asia/Seoul')).date()
        start=end-timedelta(days=days-1)
        rows=[]
        # kt00007 accepts one order date. Query weekdays only; the API will simply
        # return no rows for exchange holidays.
        cursor=end
        delay=1.05 if self.mode=='demo' else 0.22
        while cursor>=start:
            if cursor.weekday()<5:
                pages,_=self._pages('kt00007','/api/dostk/acnt',
                    {'qry_tp':'4','stk_bond_tp':'1','sell_tp':'0','dmst_stex_tp':'%',
                     'ord_dt':cursor.strftime('%Y%m%d'),'stk_cd':'','fr_ord_no':''})
                for data in pages:
                    for row in data.get('acnt_ord_cntr_prps_dtl') or []:
                        if not isinstance(row,dict):continue
                        qty=number(row.get('cntr_qty'),0)
                        if qty<=0:continue
                        side_text=str(row.get('trde_tp') or row.get('io_tp_nm') or '')
                        side='01' if ('매도' in side_text or side_text.strip()=='1') else '02' if ('매수' in side_text or side_text.strip()=='2') else ''
                        if not side:continue
                        price=clean_price(row.get('cntr_uv'))
                        rows.append({'cncl_yn':'N','tot_ccld_qty':str(qty),'sll_buy_dvsn_cd':side,
                            'pdno':str(row.get('stk_cd','')).replace('A',''),'ord_dt':cursor.strftime('%Y%m%d'),
                            'ord_tmd':str(row.get('cnfm_tm') or row.get('ord_tm') or '000000').replace(':','').zfill(6)[-6:],
                            'avg_prvs':str(price),'tot_ccld_amt':str(price*qty),'ord_gno_brno':'KIWOOM',
                            'odno':str(row.get('ord_no') or ''),'prdt_name':str(row.get('stk_nm') or row.get('stk_cd') or '')})
                time.sleep(delay)
            cursor-=timedelta(days=1)
        return {'rows':rows,'from':start.isoformat(),'to':end.isoformat(),
                'fetched':datetime.now(ZoneInfo('Asia/Seoul')).isoformat()}

    def daily_bars(self,code,end_day):
        """Adjusted daily bars before a purchase (ka10081), mapped to legacy chart fields."""
        if not re.fullmatch(r'[0-9A-Z]{6}',str(code).upper()) or not isinstance(end_day,date):
            raise BrokerError('일별 시세 조회 조건을 확인하세요.')
        cutoff=end_day-timedelta(days=1)
        pages,_=self._pages('ka10081','/api/dostk/chart',
            {'stk_cd':str(code).upper(),'base_dt':cutoff.strftime('%Y%m%d'),'upd_stkpc_tp':'1'},max_pages=2)
        rows=[]
        for data in pages:
            for row in data.get('stk_dt_pole_chart_qry') or []:
                if isinstance(row,dict):
                    rows.append({'stck_bsop_date':row.get('dt'),'stck_hgpr':clean_price(row.get('high_pric')),
                                 'stck_lwpr':clean_price(row.get('low_pric'))})
        return rows

    def index_bars(self,code,as_of=None):
        """KOSPI/KOSDAQ daily index bars (ka20009), mapped to dashboard fields."""
        if code not in ('0001','1001'):raise BrokerError('지원하지 않는 지수입니다.')
        market='0' if code=='0001' else '1'
        inds='001' if code=='0001' else '101'
        pages,_=self._pages('ka20009','/api/dostk/sect',{'mrkt_tp':market,'inds_cd':inds},max_pages=2)
        rows=[]
        for data in pages:
            for row in data.get('inds_cur_prc_daly_rept') or []:
                if isinstance(row,dict):
                    rows.append({'stck_bsop_date':row.get('dt_n'),'bstp_nmix_prpr':clean_price(row.get('cur_prc_n'))})
        return rows

    def market_flow(self,code,as_of=None):
        """Latest KOSPI/KOSDAQ investor net-buy values from ka10051."""
        if code not in ('0001','1001'):raise BrokerError('지원하지 않는 시장입니다.')
        day=as_of or datetime.now(ZoneInfo('Asia/Seoul')).date()
        market='0' if code=='0001' else '1'
        _,data=self._pages('ka10051','/api/dostk/sect',
            {'mrkt_tp':market,'amt_qty_tp':'0','stex_tp':'3','base_dt':day.strftime('%Y%m%d')},max_pages=1)
        rows=data.get('inds_netprps') or []
        target=None
        inds_code='001' if code=='0001' else '101'
        for row in rows:
            if isinstance(row,dict) and str(row.get('inds_cd','')).strip()==inds_code:
                target=row;break
        if target is None and rows:
            target=rows[0] if isinstance(rows[0],dict) else None
        if not target:raise BrokerError('키움증권 시장 수급 자료가 없습니다.')
        return {'date':day.isoformat(),'net':{
            'individual':number(target.get('ind_netprps'),0),
            'institution':number(target.get('orgn_netprps'),0),
            'foreign':number(target.get('frgnr_netprps'),0)},
            'unit':'source','source':'키움증권 업종별 투자자 순매수'}
