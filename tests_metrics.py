import sys
import types
import unittest
from datetime import date
from unittest.mock import patch

try:import requests
except ImportError:sys.modules['requests']=types.SimpleNamespace(RequestException=Exception)
from predash.official import Official,DataError
from predash.krx import daily_activity

class FinancialPeriodTests(unittest.TestCase):
    def provider(self,prior):
        obj=Official.__new__(Official)
        obj.corp=lambda code:'00126380'
        def dart(endpoint,**params):
            if params['bsns_year']!='2026' or params['reprt_code']!='11012' or params['fs_div']!='CFS':return None
            return {'list':[
                {'sj_div':'IS','account_id':'ifrs-full_Revenue','thstrm_add_amount':'20000000000','frmtrm_add_amount':'10000000000','rcept_no':'20260814000001'},
                {'sj_div':'IS','account_id':'dart_OperatingIncomeLoss','thstrm_add_amount':'3000000000','frmtrm_add_amount':prior,'rcept_no':'20260814000001'}]}
        obj.dart=dart
        return obj
    def test_same_period_cumulative_growth_and_margin(self):
        result=self.provider('2000000000').latest_period_metrics('005930',date(2026,9,29))
        self.assertEqual((result['revenue'],result['profit'],result['growth_pct'],result['margin_pct']),
                         (200,30,50,15))
        self.assertEqual((result['quarter'],result['basis']),(2,'CFS'))
    def test_nonpositive_prior_profit_holds_growth(self):
        self.assertIsNone(self.provider('-2000000000').latest_period_metrics('005930',date(2026,9,29))['growth_pct'])

    def test_quarter_standalone_is_not_half_year_total(self):
        obj=self.provider('2000000000');base=obj.dart
        def dart(endpoint,**params):
            data=base(endpoint,**params)
            if data:
                data['list'][0].update(thstrm_amount='12000000000',frmtrm_q_amount='6000000000')
                data['list'][1].update(thstrm_amount='1800000000',frmtrm_q_amount='1200000000')
            return data
        obj.dart=dart
        m=obj.latest_period_metrics('005930',date(2026,9,29))
        self.assertEqual(m['revenue'],200)
        self.assertEqual(m['standalone']['revenue'],120)
        self.assertEqual(m['standalone']['profit'],18)
        self.assertEqual(m['standalone']['growth_pct'],50)
    def test_missing_standalone_not_filled_from_cumulative(self):
        m=self.provider('2000000000').latest_period_metrics('005930',date(2026,9,29))
        self.assertIsNone(m['standalone']['profit'])
        self.assertIsNone(m['standalone']['growth_pct'])

class KRXValidationTests(unittest.TestCase):
    def test_exact_code_and_date_only(self):
        class Response:
            status_code=200
            def raise_for_status(self):pass
            def json(self):return {'OutBlock_1':[
                {'ISU_SRT_CD':'005930','BAS_DD':'20260929','ACC_TRDVOL':'1,234','ACC_TRDVAL':'123,000,000','MKTCAP':'1,000,000,000'},
                {'ISU_SRT_CD':'000660','BAS_DD':'20260929','ACC_TRDVOL':'8','ACC_TRDVAL':'8','MKTCAP':'8'}]}
        with patch('predash.krx.requests.get',return_value=Response(),create=True):
            result=daily_activity('key','005930',date(2026,9,29))
        self.assertEqual((result['volume'],result['market_cap']),(1234,1000000000))

if __name__=='__main__':unittest.main()

