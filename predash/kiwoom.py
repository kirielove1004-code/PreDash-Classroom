"""Read-only Kiwoom Securities REST adapter used by PreDash Classroom."""
from __future__ import annotations
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

class BrokerError(RuntimeError):
    pass

def number(value):
    try:
        result=float(str(value).replace(',',''))
        if result!=result or abs(result)==float('inf'):
            raise ValueError
        return result
    except (TypeError,ValueError):
        raise BrokerError('키움증권 응답의 숫자를 확인할 수 없습니다.') from None

class Kiwoom:
    def __init__(self, mode=None, *, settings=None):
        settings=settings or {}
        self.mode=mode or settings.get('mode','demo')
        self.key=str(settings.get('key','')).strip()
        self.secret=str(settings.get('secret','')).strip()
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
            response=requests.request(method,self.base+path,timeout=(5,20),**kwargs)
            if response.status_code in (401,403):
                raise BrokerError(f'키움증권 인증 거부 (HTTP {response.status_code}) · 실전/모의 환경과 App Key·Secret을 확인하세요.')
            if response.status_code==429:
                raise BrokerError('키움증권 호출 제한 (HTTP 429) · 잠시 후 다시 시도하세요.')
            response.raise_for_status()
            data=response.json()
            if not isinstance(data,dict):
                raise ValueError
            return response,data
        except BrokerError:
            raise
        except (requests.RequestException,ValueError):
            raise BrokerError('키움증권 연결 실패 · 키, 환경, 서비스 상태를 확인하세요.') from None

    def authorize(self):
        if self.token and time.time()<self.expires:
            return
        _,data=self.call('POST','/oauth2/token',
            headers={'Content-Type':'application/json;charset=UTF-8'},
            json={'grant_type':'client_credentials','appkey':self.key,'secretkey':self.secret})
        token=data.get('token') or data.get('access_token')
        if not token:
            raise BrokerError('키움증권 접근토큰 발급 실패 · App Key·Secret과 REST API 사용신청 상태를 확인하세요.')
        self.token=str(token)
        expires=data.get('expires_dt') or data.get('expires_in')
        self.expires=time.time()+3600
        if isinstance(expires,(int,float)):
            self.expires=time.time()+max(60,float(expires)-120)

    def _headers(self,api_id=None):
        self.authorize()
        h={'authorization':'Bearer '+self.token,'Content-Type':'application/json;charset=UTF-8'}
        if api_id:h['api-id']=api_id
        return h

    def balance(self):
        """Read domestic-stock evaluation balance. Kiwoom links the account to the issued app key."""
        _,data=self.call('POST','/api/dostk/acnt',
            headers=self._headers('kt00018'),json={'qry_tp':'1','dmst_stex_tp':'KRX'})
        rows=data.get('stk_acnt_evlt_prst') or data.get('acnt_evlt_remn_indv_tot') or data.get('output') or []
        if isinstance(rows,dict): rows=[rows]
        if not isinstance(rows,list):
            raise BrokerError('키움증권 잔고 조회 응답 형식을 확인하지 못했습니다.')
        positions=[]
        for row in rows:
            code=str(row.get('stk_cd') or row.get('code') or row.get('pdno') or '').replace('A','')
            qty_raw=row.get('rmnd_qty') if row.get('rmnd_qty') is not None else row.get('hldg_qty')
            if qty_raw in (None,''): continue
            qty=number(qty_raw)
            if qty<=0: continue
            price=number(row.get('cur_prc') or row.get('prpr') or 0)
            value=number(row.get('evlt_amt') or row.get('evlu_amt') or price*qty)
            pnl=number(row.get('pl_amt') or row.get('evlu_pfls_amt') or 0)
            avg=number(row.get('pur_pric') or row.get('pchs_avg_pric') or 0)
            positions.append({'code':code.zfill(6),'name':row.get('stk_nm') or row.get('name') or code,
                'quantity':qty,'average_cost':avg,'price':price,'value':value,'pnl':pnl})
        total=sum(p['value'] for p in positions)
        for p in positions:p['weight']=p['value']/total*100 if total>0 else 0
        return {'positions':positions,'value':total,'pnl':sum(p['pnl'] for p in positions),
                'cash':None,'mode':self.mode,'fetched':datetime.now(ZoneInfo('Asia/Seoul')).isoformat()}

    def investor_flow(self,code):
        raise BrokerError('키움증권 수급 조회는 다음 단계에서 연결 예정입니다.')

    def fills(self,days=30):
        raise BrokerError('키움증권 체결내역 조회는 다음 단계에서 연결 예정입니다.')

    def market_flow(self,code,as_of=None):
        raise BrokerError('키움증권 시장 수급 조회는 다음 단계에서 연결 예정입니다.')

    def daily_bars(self,code,end_day):
        raise BrokerError('키움증권 과거 일별시세 조회는 다음 단계에서 연결 예정입니다.')

    def index_bars(self,code,as_of=None):
        raise BrokerError('키움증권 지수 일별시세 조회는 다음 단계에서 연결 예정입니다.')
