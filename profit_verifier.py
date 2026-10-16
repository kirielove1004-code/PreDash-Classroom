"""PlanX 04 / 03 PROFIT. Official CFS only; never replace absent amounts by zero."""
import calendar
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

CODES = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
GUIDE = 'https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020'


class VerificationError(ValueError):
    pass


def number(value):
    if value is None or str(value).strip() in ('', '-', '—'):
        return None
    text = str(value).replace(',', '').strip()
    if text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1]
    try:
        n = Decimal(text)
        return n if n.is_finite() else None
    except InvalidOperation:
        return None


def change(now, before):
    if now is None or before is None:
        return '미확인 · 원자료 필요'
    delta = now - before
    formula = f'금액 변화 = {fmt(now)} − ({fmt(before)}) = {fmt(delta)}'
    if before == 0:
        return '계산 불가 · 전년 0; ' + formula
    if now < 0 or before < 0:
        state = ('흑자전환' if now > 0 else '손익분기 도달') if before < 0 <= now else (
            '적자전환' if before > 0 > now else '적자 축소' if delta > 0 else '적자 확대' if delta < 0 else '적자 유지')
        return state + '; ' + formula
    return f'{(now-before)/before*100:+.2f}% = ({fmt(now)} − {fmt(before)}) ÷ {fmt(before)} × 100'


def fmt(n):
    return '미확인' if n is None else f'{n:,.0f}'


def margin(revenue, profit):
    return None if revenue in (None, 0) or profit is None else profit / revenue * 100


def select_account(rows, kind, corp, year, quarter):
    ids, names = ({'ifrs-full_Revenue', 'ifrs_Revenue'}, {'매출액', '수익(매출액)', '매출'}) if kind == '매출' else (
        {'dart_OperatingIncomeLoss'}, {'영업이익', '영업이익(손실)', '영업손실'})
    eligible = [r for r in rows if r.get('sj_div') in ('IS', 'CIS')
                and str(r.get('corp_code')) == corp and str(r.get('bsns_year')) == str(year)
                and r.get('reprt_code') == CODES[quarter]]
    matched = [r for r in eligible if r.get('account_id') in ids]
    if not matched:
        matched = [r for r in eligible if r.get('account_nm', '').replace(' ', '') in names]
    # Duplicate IS/CIS rows are acceptable only when all material fields agree.
    fields = ('currency', 'rcept_no', 'thstrm_amount', 'thstrm_add_amount', 'frmtrm_q_amount', 'frmtrm_add_amount', 'frmtrm_amount')
    if not matched:
        raise VerificationError(kind + ' 계정을 확인하지 못했습니다. 연결 손익계산서 계정 확인 필요')
    if len({tuple(r.get(k) for k in fields) for r in matched}) != 1:
        raise VerificationError(kind + ' 계정 후보가 중복·불일치합니다. 임의 합산하지 않습니다.')
    return matched[0]


def filings(client, corp, today):
    records = []
    page = 1
    while True:
        p = client.dart('list.json', corp_code=corp, bgn_de=f'{today.year-3}0101',
                        end_de=today.strftime('%Y%m%d'), pblntf_ty='A', last_reprt_at='Y',
                        page_count=100, page_no=page) or {}
        for row in p.get('list', []):
            name = row.get('report_nm', '')
            m = re.search(r'(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)', name)
            if not m:
                continue
            y, month = int(m[2]), int(m[3])
            q = {3: 1, 6: 2, 9: 3, 12: 4}.get(month)
            if q and ((m[1] == '사업' and q == 4) or (m[1] == '반기' and q == 2) or (m[1] == '분기' and q in (1, 3))):
                records.append({**row, 'year': y, 'quarter': q})
        if page >= int(p.get('total_page', 1)):
            break
        page += 1
    if not records:
        raise VerificationError('실제 제출된 정기보고서가 없습니다. 최신 공시 목록 확인 필요')
    return records


def fetch(client, code):
    today = datetime.now(ZoneInfo('Asia/Seoul')).date()
    corp = client.corp(code)
    info = client.dart('company.json', corp_code=corp) or {}
    if str(info.get('acc_mt', '')).zfill(2) != '12':
        raise VerificationError('12월 결산 여부 미확인 또는 비12월 결산: 회계기간을 수동 검토해야 합니다.')
    records = filings(client, corp, today)
    latest = max(records, key=lambda r: (r['year'], r['quarter'], r['rcept_no']))
    y, q = latest['year'], latest['quarter']
    used = []

    def statement(year, quarter):
        candidates = [r for r in records if r['year'] == year and r['quarter'] == quarter]
        if not candidates:
            raise VerificationError(f'{year} Q{quarter} 제출 공시가 없어 차감 계산을 보류합니다.')
        filing = max(candidates, key=lambda r: r['rcept_no'])
        p = client.dart('fnlttSinglAcntAll.json', corp_code=corp, bsns_year=str(year),
                        reprt_code=CODES[quarter], fs_div='CFS') or {}
        rows = {k: select_account(p.get('list', []), k, corp, year, quarter) for k in ('매출', '영업이익')}
        if any(r.get('rcept_no') != filing['rcept_no'] for r in rows.values()):
            raise VerificationError('재무 API와 최신 정정공시 접수번호 불일치: 최신 원문 확인 필요')
        if len({r.get('currency') for r in rows.values()}) != 1 or not all(r.get('currency') for r in rows.values()):
            raise VerificationError('매출·영업이익 통화 불일치 또는 미확인')
        used.append({'filing': filing, 'rows': rows})
        return rows

    rows = statement(y, q)
    annual = q == 4
    cumulative = {k: (number(r.get('thstrm_amount' if annual else 'thstrm_add_amount')),
                       number(r.get('frmtrm_amount' if annual else 'frmtrm_add_amount'))) for k, r in rows.items()}
    quarterly = {k: (None, None) if annual else (number(r.get('thstrm_amount')), number(r.get('frmtrm_q_amount')))
                 for k, r in rows.items()}
    needs_diff = any(v is None for pair in quarterly.values() for v in pair)
    formulas = []
    warnings = []
    if needs_diff:
        if q == 1:
            for k in quarterly:
                quarterly[k] = tuple(v if v is not None else cumulative[k][i] for i, v in enumerate(quarterly[k]))
            formulas.append('Q1의 누적과 3개월 기간은 동일합니다. 원문 확인 후 사용합니다.')
        else:
            try:
                previous = statement(y, q-1)
                previous_year = statement(y-1, q) if annual else None
                for k, r in rows.items():
                    p = previous[k]
                    if p['currency'] != r['currency'] or (previous_year and previous_year[k]['currency'] != r['currency']):
                        raise VerificationError('차감 대상 통화 불일치')
                    prior_total = cumulative[k][1]
                    # Restated annual prior values must equal prior-year annual original before using its Q3.
                    if annual and number(previous_year[k].get('thstrm_amount')) != prior_total:
                        raise VerificationError('전년 연간 비교값과 전년 공시 원자료 불일치 · 정정/재작성 검토 필요')
                    base = (number(p.get('thstrm_add_amount')), number(p.get('frmtrm_add_amount')))
                    values = []
                    for i, v in enumerate(quarterly[k]):
                        a, b = cumulative[k][i], base[i]
                        if v is None:
                            v = None if a is None or b is None else a-b
                            formulas.append(f'{k} {"당기" if i == 0 else "전년"} Q{q} = {fmt(a)} − {fmt(b)} = {fmt(v)}')
                        values.append(v)
                    quarterly[k] = tuple(values)
                warnings.append('차감값: 정정·회계정책·연결범위·기간이 동일하고 누적 합계가 일치하는지 원문 확인 필요')
            except VerificationError as exc:
                warnings.append(str(exc))
    currencies = {r['currency'] for entry in used for r in entry['rows'].values()}
    if len(currencies) != 1:
        raise VerificationError('원자료 통화가 다릅니다.')
    result = {'company': info.get('corp_name', code), 'code': code, 'corp': corp, 'date': today.isoformat(),
            'year': y, 'quarter': q, 'currency': next(iter(currencies)), 'cumulative': cumulative,
            'quarterly': quarterly, 'used': used, 'formulas': formulas, 'warnings': warnings}
    from profit_xbrl import verify
    result['verification'] = verify(result, client, info)
    return result


def periods(year, q):
    month = q*3
    end = f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}'
    return f'{year}-01-01 ~ {end}', f'{year}-{month-2:02d}-01 ~ {end}'


def verdict(data, verified):
    if not verified or any(v is None for section in ('cumulative', 'quarterly') for pair in data[section].values() for v in pair):
        return '보류', '원문 검증 또는 비교 원자료가 부족합니다.'
    for section in ('cumulative', 'quarterly'):
        r, p = data[section]['매출'], data[section]['영업이익']
        if r[0] <= 0 or r[1] <= 0 or margin(r[0], p[0]) is None:
            return '보류', '매출이 0 이하이거나 증가율·이익률 비교 조건이 부족합니다.'
    # PROFIT alone cannot establish price attractiveness or a buy recommendation.
    return '관찰', '매출·영업이익만 검증한 단계입니다. 아래 세 문장으로 흐름을 확인하세요.'


def summary(data, verified):
    if not verified:
        return ['매출 성장은 원문 기간 확인 전이라 판단을 보류합니다.',
                '이익 성장은 원문 금액과 합계 확인 전이라 판단을 보류합니다.',
                '이익률 변화는 통화·연결 기준 확인 전이라 판단을 보류합니다.']
    sentences = []
    for k in ('매출', '영업이익'):
        parts = []
        for label, section in (('누적', 'cumulative'), ('최신 분기', 'quarterly')):
            a, b = data[section][k]
            parts.append(label + ' ' + change(a, b).split(';')[0].split(' = ')[0])
        sentences.append(k + '은 전년 동기 대비 ' + ', '.join(parts) + '.')
    parts = []
    for label, section in (('누적', 'cumulative'), ('최신 분기', 'quarterly')):
        r, p = data[section]['매출'], data[section]['영업이익']
        a, b = margin(r[0], p[0]), margin(r[1], p[1])
        parts.append(label + (' 계산 불가' if a is None or b is None else f' {a-b:+.2f}%p'))
    return sentences + ['매출에서 영업이익으로 남는 비율의 전년 동기 대비 변화는 ' + ', '.join(parts) + '.']


def render(client_factory):
    import streamlit as st
    st.header('03 PROFIT · 재무제표 검증')
    st.caption('04회 · 재무제표를 쉽게 읽는 법 | PlanX 투자 검증자 | 공식 연결 재무제표만 사용')
    st.write('기간 맞추기 → 누적 동기 비교 → 분기 동기 비교 → 증가율 → 이익률 변화')
    with st.form('profit_lookup'):
        code = st.text_input('종목코드 6자리', placeholder='005930')
        submitted = st.form_submit_button('최신 제출 공시로 검증', type='primary')
    if submitted:
        st.session_state.pop('profit_result', None)
        if not re.fullmatch(r'\d{6}', code.strip()):
            st.error('숫자 6자리 종목코드를 입력하세요.')
        else:
            try:
                with st.spinner('DART 최신 공시·연결 재무제표 확인 중'):
                    data = fetch(client_factory(), code.strip())
                st.session_state['profit_result'] = data
                st.session_state['profit_generation'] = st.session_state.get('profit_generation', 0) + 1
            except VerificationError as exc:
                st.error('보류 · ' + str(exc))
            except Exception:
                st.error('보류 · DART 조회 또는 원자료 검증 실패. 연결 설정의 DART 진단과 최신 연결 공시·매출·영업이익 계정을 확인하세요.')
                st.caption('추가 필요: 최신 정기공시, 연결 손익계산서의 기간·통화·당기/전년 금액. 인증키는 화면에 표시하지 않습니다.')
    d = st.session_state.get('profit_result')
    if not d:
        st.info('종목을 조회하면 누적·분기 비교표와 원자료 검증 화면이 나옵니다. 자료가 없으면 판정은 보류입니다.')
        return
    st.subheader(d['company'] + ' · ' + d['code'])
    cp, qp = periods(d['year'], d['quarter'])
    pc, pq = periods(d['year']-1, d['quarter'])
    st.write({'출처기관': '금융감독원 OpenDART', 'API': 'list.json / company.json / fnlttSinglAcntAll.json',
              '조회일(KST)': d['date'], '사업연도': d['year'], '보고서코드': CODES[d['quarter']],
              '누적 당기 / 전년': cp + ' / ' + pc, '분기 당기 / 전년': qp + ' / ' + pq,
              '단위': d['currency'] + ' 기본 통화단위(축약 없음)', '연결/별도': 'CFS 연결',
              '잠정/확정': '제출 정기보고서 · 잠정실적 미사용, 감사/검토 의견 미확인'})
    st.caption('비교 대상 기간입니다. 아래 자동 검증 증거의 XBRL 실제 시작·종료일과 일치해야 판정합니다.')
    with st.expander('확인된 사실 · API 원자료와 공시 원문', expanded=True):
        for entry in d['used']:
            f = entry['filing']
            st.link_button(f['report_nm'] + ' · ' + f['rcept_no'],
                           'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + f['rcept_no'])
            st.json(entry['rows'])
        st.link_button('OpenDART 필드 정의', GUIDE)
        st.download_button('검증용 원자료 JSON 내려받기', __import__('json').dumps(d, ensure_ascii=False, default=str, indent=2),
                           file_name='planx_profit_' + d['code'] + '.json', mime='application/json')
    for warning in d['warnings']:
        st.warning(warning)
    st.subheader('XBRL 원본 자동 대조')
    v = d['verification']
    verified = v['verified']
    st.write('자동 검증 완료' if verified else '보류 · 원본 불일치 또는 확인 불가')
    st.caption('금융감독원 fnlttXbrl.xml · 최신 최종공시와 동일 접수번호의 원본에서 기업 식별자·연결 차원·실제 기간·ISO 통화·계정·금액을 대조합니다.')
    for issue in v.get('issues', []):
        st.warning(issue)
    with st.expander('자동 검증 증거 · 실제 기간/단위/연결 컨텍스트'):
        st.json(v)
    if not verified:
        st.warning('검증 전 미확인: 아래 수치는 API 필드 기준 계산 미리보기입니다. 최종 판정은 보류합니다.')
    for title, section in (('누적 전년 동기 비교', 'cumulative'), ('최신 분기 전년 동기 비교', 'quarterly')):
        st.subheader(title)
        pairs = d[section]
        st.table([{'항목': k, '전년 동기': fmt(b), '당기': fmt(a), '증가율 / 상태 · 계산식': change(a, b)}
                  for k, (a, b) in pairs.items()])
        r, p = pairs['매출'], pairs['영업이익']
        a, b = margin(r[0], p[0]), margin(r[1], p[1])
        st.write('영업이익률 = 영업이익 ÷ 매출 × 100')
        st.write('당기: ' + ('계산 불가' if a is None else f'{fmt(p[0])} ÷ {fmt(r[0])} × 100 = {a:.2f}%'))
        st.write('전년: ' + ('계산 불가' if b is None else f'{fmt(p[1])} ÷ {fmt(r[1])} × 100 = {b:.2f}%'))
        st.write('이익률 변화: ' + ('계산 불가' if a is None or b is None else f'{a:.2f}% − {b:.2f}% = {a-b:+.2f}%p'))
    if d['formulas']:
        st.write('분기 도출식 · 원단위')
        for line in d['formulas']:
            st.write(line)
    st.caption('연간 누적은 thstrm_amount / frmtrm_amount, 분·반기 누적은 thstrm_add_amount / frmtrm_add_amount. 분·반기 3개월은 thstrm_amount / frmtrm_q_amount. frmtrm_amount를 분기 동기로 쓰지 않습니다.')
    st.subheader('실적 흐름 · 해석 3문장')
    for sentence in summary(d, verified):
        st.write(sentence)
    decision, reason = verdict(d, verified)
    st.subheader('마지막 판정: ' + decision)
    st.write(reason)
    st.write('판정 폐기 조건: 정정공시로 비교 금액이 바뀌거나, 기간·통화·연결 기준 불일치가 확인되면 현재 판정을 폐기하고 재검증합니다.')
    st.caption('미확인: 뉴스·기업 주장, 주가 적정성, 현금흐름·재무안정성. 이 단계에서는 매수·기업 폐기를 단정하지 않습니다.')
