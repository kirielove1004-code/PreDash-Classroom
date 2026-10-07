import unittest
from datetime import date
from unittest.mock import Mock,patch
import requests
from predash.krx import daily_activity,diagnose_krx,KRXError

ASOF=date(2026,10,7)
def response(status,rows=None):
    r=Mock(status_code=status)
    r.json.return_value={'OutBlock_1':rows}
    return r

class KRXDiagnosticsTests(unittest.TestCase):
    def test_kospi_rejection_does_not_stop_approved_kosdaq(self):
        row={'ISU_SRT_CD':'035900','BAS_DD':'20261007','ACC_TRDVOL':'10','ACC_TRDVAL':'1000','MKTCAP':'10000'}
        with patch('predash.krx.requests.get',side_effect=[response(401),response(200,[row])]) as get,patch('predash.krx._cached_daily_activity') as fallback:
            r=daily_activity('test','035900',ASOF)
        self.assertFalse(r['fallback']);self.assertEqual(r['market'],'코스닥');fallback.assert_not_called()
        self.assertEqual(get.call_args.kwargs['headers'],{'AUTH_KEY':'test'})
    def test_all_rejected_calls_each_service_once_then_falls_back(self):
        with patch('predash.krx.requests.get',side_effect=[response(401),response(403)]) as get,patch('predash.krx._cached_daily_activity',return_value={'date':'2026-10-06','fallback':True}):
            r=daily_activity('test','005930',ASOF)
        self.assertEqual(get.call_count,2);self.assertTrue(r['fallback'])
        self.assertIn('403',r['official_error'])
    def test_diagnostic_partial_service_does_not_call_key_invalid(self):
        with patch('predash.krx.requests.get',side_effect=[response(401),response(200,[{}]),response(401),response(403)]),patch('predash.krx.daily_activity') as fallback:
            r=diagnose_krx('test',ASOF)
        self.assertEqual(r['status'],'부분 정상');self.assertEqual(len(r['services']),4)
        fallback.assert_not_called();self.assertNotIn('키 오류',r['detail'])
    def test_diagnostic_auth_failures_keep_distinct_codes(self):
        with patch('predash.krx.requests.get',side_effect=[response(401),response(403),response(401),response(403)]),patch('predash.krx.daily_activity',return_value={'date':'2026-10-06'}):
            r=diagnose_krx('test',ASOF)
        self.assertEqual(r['status'],'대체 사용 중')
        self.assertEqual([x['http'] for x in r['services']],[401,403,401,403])
        self.assertIn('확정할 수 없습니다',r['detail']);self.assertIn('복구된 것은 아닙니다',r['detail'])
    def test_all_normal_empty_rows_are_not_auth_failures(self):
        with patch('predash.krx.requests.get',return_value=response(200,[])),patch('predash.krx.daily_activity') as fallback:
            r=diagnose_krx('test',ASOF)
        self.assertEqual(r['status'],'정상');fallback.assert_not_called()
    def test_timeout_not_reported_as_invalid_key(self):
        with patch('predash.krx.requests.get',side_effect=requests.Timeout),patch('predash.krx.daily_activity',side_effect=KRXError):
            r=diagnose_krx('test',ASOF)
        self.assertEqual(r['status'],'응답 지연');self.assertTrue(all(x['http'] is None for x in r['services']))
    def test_malformed_200_not_reported_healthy(self):
        with patch('predash.krx.requests.get',return_value=response(200)),patch('predash.krx.daily_activity',side_effect=KRXError):
            r=diagnose_krx('test',ASOF)
        self.assertEqual(r['status'],'연결 확인 필요')
    def test_diagnostic_never_echoes_key_or_response_body(self):
        r=response(401);r.text='test-secret in provider response'
        with patch('predash.krx.requests.get',return_value=r),patch('predash.krx.daily_activity',side_effect=KRXError):
            result=diagnose_krx('test-secret',ASOF)
        self.assertNotIn('test-secret',str(result))

if __name__=='__main__':unittest.main()
