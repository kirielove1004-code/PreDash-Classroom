import copy
import json
import unittest
from datetime import date
from unittest.mock import Mock
from predash.opportunities import (SCORE_LIMITS,FACT_LABELS,ResearchError,call_gemini,
    normalize_stock,discovery_candidates,table_rows,export_records,restore_records)

ASOF=date(2026,10,7)

def packet():
    evidence='시험용 공시 수치와 비교 근거 2026-10-06'
    return {'data':{'code':'267260','name':'시험기업','sector':'시험업종',
        'facts':{k:{'value':100 if k in ('current_price','target_avg') else 10,
                    'asof':'2026-10-06','evidence':evidence} for k in FACT_LABELS},
        'scores':[{'area':a,'score':v,'asof':'2026-10-06','evidence':evidence} for a,v in SCORE_LIMITS.items()],
        'total':9999,'grade':'S','risks':['시험 위험']},
        'sources':[{'index':0,'url':'https://example.com/test','title':'시험 출처'}],
        'supports':[{'segment':{'text':evidence},'groundingChunkIndices':[0]}]}

class OpportunityTests(unittest.TestCase):
    def test_total_and_grade_recomputed(self):
        record=normalize_stock(packet(),'267260',ASOF)
        self.assertEqual(record['total'],120);self.assertEqual(record['grade'],'S')
        self.assertEqual(record['status'],'우선 검토')
    def test_no_source_or_grounding_never_scores(self):
        p=packet();p['supports']=[]
        r=normalize_stock(p,'267260',ASOF)
        self.assertIsNone(r['total']);self.assertEqual(r['coverage'],0)
        self.assertTrue(all(x['value'] is None for x in r['facts'].values()))
    def test_one_missing_score_blocks_total_not_scaled(self):
        p=packet();p['data']['scores'][2]['score']=None
        r=normalize_stock(p,'267260',ASOF)
        self.assertIsNone(r['total']);self.assertEqual(r['coverage'],7)
    def test_invalid_numbers_and_dates_block_scores(self):
        for bad in [True,float('nan'),float('inf'),21,-1,10.5,'20']:
            with self.subTest(bad=bad):
                p=packet();p['data']['scores'][0]['score']=bad
                self.assertIsNone(normalize_stock(p,'267260',ASOF)['total'])
        for bad in ['2026-10-08','2020-01-01','']:
            p=packet();p['data']['scores'][0]['asof']=bad
            self.assertIsNone(normalize_stock(p,'267260',ASOF)['total'])
    def test_stale_price_and_duplicate_scores_block_ranking(self):
        p=packet();p['data']['facts']['current_price']['asof']='2026-09-01'
        self.assertIsNone(normalize_stock(p,'267260',ASOF)['total'])
        p=packet();p['data']['scores'].append(p['data']['scores'][0])
        self.assertIsNone(normalize_stock(p,'267260',ASOF)['total'])
    def test_official_price_overrides_ai_and_upside_calculated(self):
        obs={'price':{'value':50,'asof':'2026-10-06','source':'https://example.com/official'}}
        r=normalize_stock(packet(),'267260',ASOF,obs)
        self.assertEqual(r['facts']['current_price']['value'],50)
        self.assertEqual(table_rows([r])[0]['목표가 괴리율(%)'],100)
    def test_zero_score_is_known_not_missing(self):
        p=packet()
        for s in p['data']['scores']:s['score']=0
        r=normalize_stock(p,'267260',ASOF)
        self.assertEqual(r['total'],0);self.assertEqual(r['grade'],'D')
    def test_wrong_ticker_is_rejected(self):
        with self.assertRaises(ResearchError):normalize_stock(packet(),'005930',ASOF)
    def test_discovery_rejects_unlinked_and_duplicate_codes(self):
        p=packet();ev=p['data']['scores'][0]['evidence']
        p['data']={'candidates':[{'code':'267260','evidence':ev},{'code':'267260','evidence':ev},
             {'code':'005930','evidence':'해당 출처가 없는 주장'}, {'code':'invalid','evidence':ev}]}
        self.assertEqual([c['code'] for c in discovery_candidates(p,5)],['267260'])
    def test_backup_revalidates_instead_of_trusting_totals(self):
        r=normalize_stock(packet(),'267260',ASOF);data=json.loads(export_records([r]))
        data['records'][0]['total']=999
        self.assertEqual(restore_records(json.dumps(data))[0]['total'],120)
        data['records'][0]['packet']['supports']=[]
        self.assertIsNone(restore_records(json.dumps(data))[0]['total'])
    def test_api_error_does_not_expose_key_or_provider_body(self):
        post=Mock(return_value=Mock(status_code=403,text='key=private-key'))
        with self.assertRaises(ResearchError) as e:call_gemini('private-key','gemini-2.5-flash','prompt',post)
        self.assertNotIn('private-key',str(e.exception))
        self.assertEqual(post.call_args.kwargs['headers']['x-goog-api-key'],'private-key')
    def test_no_search_response_is_rejected(self):
        post=Mock(return_value=Mock(status_code=200,json=lambda:{'candidates':[{
            'content':{'parts':[{'text':'{"code":"267260"}'}]},'finishReason':'STOP'}]}))
        with self.assertRaises(ResearchError):call_gemini('test','gemini-2.5-flash','prompt',post)

if __name__=='__main__':unittest.main()
