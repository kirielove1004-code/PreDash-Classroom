import io
import unittest
import zipfile
from decimal import Decimal as D
from profit_verifier import change, margin, select_account, verdict, summary, periods
from profit_xbrl import collect, exact, verify


def archive(body):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('financial.xbrl', body)
    return output.getvalue()


def fixture(member='ConsolidatedMember', end='2026-06-30', extra=''):
    return archive(f'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi" xmlns:ifrs-full="http://xbrl.ifrs.org/taxonomy/2026/ifrs-full"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
      <xbrli:context id="c"><xbrli:entity><xbrli:identifier scheme="dart">00126380</xbrli:identifier>
      <xbrli:segment><xbrldi:explicitMember dimension="ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis">ifrs-full:{member}</xbrldi:explicitMember>{extra}</xbrli:segment>
      </xbrli:entity><xbrli:period><xbrli:startDate>2026-01-01</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>
      <xbrli:unit id="won"><xbrli:measure>iso4217:KRW</xbrli:measure></xbrli:unit>
      <ifrs-full:Revenue contextRef="c" unitRef="won" decimals="0">120</ifrs-full:Revenue></xbrli:xbrl>''')


class ProfitTests(unittest.TestCase):
    def test_absent_and_zero(self):
        self.assertIn('미확인', change(None, D(1)))
        self.assertIn('계산 불가', change(D(10), D(0)))
        self.assertIsNone(margin(D(0), D(1)))
        self.assertIsNone(margin(D(100), None))

    def test_negative_transitions(self):
        for a, b, label in ((2,-1,'흑자전환'),(-2,1,'적자전환'),(-1,-2,'적자 축소'),(-2,-1,'적자 확대')):
            self.assertIn(label, change(D(a), D(b)))
            self.assertIn('금액 변화', change(D(a), D(b)))
        self.assertIn('+20.00%', change(D(120), D(100)))

    def test_xbrl_exact(self):
        facts = collect(fixture(), {'00126380'})
        self.assertEqual(exact(facts,'ifrs-full_Revenue','2026-01-01','2026-06-30','KRW')['value'], D(120))
        self.assertIsNone(exact(facts,'ifrs-full_Revenue','2026-04-01','2026-06-30','KRW'))
        self.assertIsNone(exact(facts,'ifrs-full_Revenue','2026-01-01','2026-06-30','USD'))

    def test_separate_segment_wrong_entity_blocked(self):
        self.assertEqual(collect(fixture('SeparateMember'), {'00126380'}), [])
        self.assertEqual(collect(fixture(), {'00999999'}), [])
        extra='<xbrldi:explicitMember dimension="ifrs-full:OperatingSegmentsAxis">ifrs-full:SegmentMember</xbrldi:explicitMember>'
        self.assertEqual(collect(fixture(extra=extra), {'00126380'}), [])

    def test_conflicting_facts_blocked(self):
        facts = collect(fixture(), {'00126380'})
        facts += [{**facts[0], 'value': D(999)}]
        self.assertIsNone(exact(facts, 'ifrs-full_Revenue','2026-01-01','2026-06-30','KRW'))

    def test_duplicate_accounts_blocked(self):
        row={'sj_div':'IS','corp_code':'00126380','bsns_year':'2026','reprt_code':'11012',
             'account_id':'ifrs-full_Revenue','thstrm_amount':'10'}
        with self.assertRaises(ValueError):
            select_account([row,{**row,'thstrm_amount':'20'}], '매출','00126380',2026,2)

    def test_verdict_and_three_sentences(self):
        d={s:{'매출':(D(120),D(100)), '영업이익':(D(15),D(10))} for s in ('cumulative','quarterly')}
        self.assertEqual(verdict(d,False)[0],'보류')
        self.assertEqual(verdict(d,True)[0],'관찰')
        self.assertEqual(len(summary(d,True)),3)
        d['quarterly']['영업이익']=(None,D(10))
        self.assertEqual(verdict(d,True)[0],'보류')

    def test_periods_leap_year(self):
        self.assertEqual(periods(2024,1)[1], '2024-01-01 ~ 2024-03-31')
        self.assertEqual(periods(2026,4)[1], '2026-10-01 ~ 2026-12-31')

    def test_unavailable_xbrl_never_passes(self):
        data={'corp':'00126380','used':[{'filing':{'rcept_no':'20260814000000'},'rows':{'매출':{'reprt_code':'11012'}}}]}
        self.assertFalse(verify(data, None, {}, download=lambda *args:b'not a zip')['verified'])

    def test_eight_original_facts_pass_and_mismatch_blocks(self):
        from copy import deepcopy
        xml = fixture()
        with zipfile.ZipFile(io.BytesIO(xml)) as z:
            text = z.read('financial.xbrl').decode()
        contexts = []
        facts = []
        for year in (2026, 2025):
            for section, month in (('cumulative','01'), ('quarterly','04')):
                cid = str(year)+section
                context = text[text.index('<xbrli:context'):text.index('</xbrli:context>')+len('</xbrli:context>')]
                context = context.replace('id="c"',f'id="{cid}"').replace('2026-',f'{year}-').replace(f'{year}-01-01',f'{year}-{month}-01')
                contexts.append(context)
                for concept, value in (('Revenue', 120 if year==2026 else 100), ('OperatingIncomeLoss',15 if year==2026 else 10)):
                    prefix='ifrs-full' if concept=='Revenue' else 'dart'
                    facts.append(f'<{prefix}:{concept} contextRef="{cid}" unitRef="won">{value}</{prefix}:{concept}>')
        root=text[:text.index('<xbrli:context')].replace('xmlns:iso4217=', 'xmlns:dart="http://dart.fss.or.kr/taxonomy/2026" xmlns:iso4217=')
        unit='<xbrli:unit id="won"><xbrli:measure>iso4217:KRW</xbrli:measure></xbrli:unit>'
        raw=archive(root+''.join(contexts)+unit+''.join(facts)+'</xbrli:xbrl>')
        data={s:{'매출':(D(120),D(100)), '영업이익':(D(15),D(10))} for s in ('cumulative','quarterly')}
        data.update(corp='00126380',year=2026,quarter=2,currency='KRW',used=[{
            'filing':{'rcept_no':'20260814000000','report_nm':'반기보고서 (2026.06)'},
            'rows':{'매출':{'reprt_code':'11012','account_id':'ifrs-full_Revenue'},
                    '영업이익':{'reprt_code':'11012','account_id':'dart_OperatingIncomeLoss'}}}])
        result=verify(data,None,{},download=lambda *args:raw)
        self.assertTrue(result['verified'],result)
        self.assertEqual(len(result['evidence']),8)
        data['quarterly']['매출']=(D(999),D(100))
        self.assertFalse(verify(data,None,{},download=lambda *args:raw)['verified'])


if __name__ == '__main__':
    unittest.main()
