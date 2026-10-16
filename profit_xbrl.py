"""Conservative XBRL evidence: exact concept, entity, CFS, currency and duration."""
import io
import re
import zipfile
from decimal import Decimal
from xml.etree import ElementTree as ET

XBRLI = 'http://www.xbrl.org/2003/instance'
XBRLDI = 'http://xbrl.org/2006/xbrldi'
XLINK = '{http://www.w3.org/1999/xlink}'


def local(tag):
    return tag.rsplit('}', 1)[-1]


def unpack(raw):
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise ValueError('XBRL 원본 ZIP 미제공 · 공개 여부/서비스 응답 확인 필요')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        files = archive.infolist()
        if sum(f.file_size for f in files) > 100_000_000:
            raise ValueError('XBRL 압축 해제 크기 제한 초과')
        roots, defaults = [], set()
        for f in files:
            if not f.filename.lower().endswith(('.xml', '.xbrl')) or f.file_size > 40_000_000:
                continue
            data = archive.read(f)
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                raise ValueError('허용되지 않은 XML 선언')
            try:
                ns = dict(value for event, value in ET.iterparse(io.BytesIO(data), events=('start-ns',)))
                root = ET.fromstring(data)
            except ET.ParseError:
                continue
            if root.tag == '{' + XBRLI + '}xbrl':
                roots.append((root, ns))
            for link in root.iter():
                locs = {n.get(XLINK+'label'): n.get(XLINK+'href', '').split('#')[-1] for n in link
                        if local(n.tag) == 'loc'}
                for arc in link:
                    if arc.get(XLINK+'arcrole', '').endswith('/dimension-default'):
                        axis = locs.get(arc.get(XLINK+'from'), '')
                        member = locs.get(arc.get(XLINK+'to'), '')
                        if axis.endswith('ConsolidatedAndSeparateFinancialStatementsAxis'):
                            defaults.add(member.rsplit('_', 1)[-1])
        return roots, defaults


def collect(raw, identifiers):
    roots, defaults = unpack(raw)
    facts = []
    for root, ns in roots:
        contexts = {}
        for c in root.findall('{' + XBRLI + '}context'):
            ident = c.find('.//{' + XBRLI + '}identifier')
            if ident is None or re.sub(r'\D', '', ident.text or '') not in identifiers:
                continue
            period = c.find('{' + XBRLI + '}period')
            if period is None:
                continue
            start = period.findtext('{' + XBRLI + '}startDate')
            end = period.findtext('{' + XBRLI + '}endDate')
            if not start or not end:
                continue
            members = c.findall('.//{' + XBRLDI + '}explicitMember')
            consolidated = defaults == {'ConsolidatedMember'}
            valid = not c.findall('.//{' + XBRLDI + '}typedMember')
            for member in members:
                axis = member.get('dimension', '').split(':')[-1]
                value = (member.text or '').split(':')[-1]
                if axis == 'ConsolidatedAndSeparateFinancialStatementsAxis':
                    consolidated = value == 'ConsolidatedMember'
                else:
                    # Segment/member facts must never be mistaken for whole-company revenue.
                    valid = False
            if valid and consolidated:
                contexts[c.get('id')] = (start[:10], end[:10])
        units = {}
        for unit in root.findall('{' + XBRLI + '}unit'):
            measures = unit.findall('{' + XBRLI + '}measure')
            if len(measures) == 1 and len(list(unit)) == 1:
                measure = measures[0].text or ''
                prefix, _, cur = measure.partition(':')
                if ns.get(prefix) == 'http://www.xbrl.org/2003/iso4217':
                    units[unit.get('id')] = cur
        for fact in root:
            ref, unit = fact.get('contextRef'), fact.get('unitRef')
            if ref not in contexts or unit not in units or fact.get('{http://www.w3.org/2001/XMLSchema-instance}nil') == 'true':
                continue
            try:
                value = Decimal((fact.text or '').strip())
                if not value.is_finite():
                    continue
            except Exception:
                continue
            facts.append({'concept': local(fact.tag), 'namespace': fact.tag.split('}')[0].lstrip('{'),
                          'start': contexts[ref][0], 'end': contexts[ref][1], 'currency': units[unit],
                          'value': value, 'context': ref, 'basis': 'CFS', 'entity_verified': True})
    return facts


def exact(facts, account, start, end, currency):
    prefix, sep, concept = account.partition('_')
    if not sep or prefix not in ('ifrs-full', 'ifrs', 'dart'):
        return None
    candidates = [f for f in facts if f['concept'] == concept and f['start'] == start and f['end'] == end
                  and f['currency'] == currency and (
                      ('xbrl.ifrs.org' in f['namespace'] or 'www.iasb.org' in f['namespace']) if prefix.startswith('ifrs')
                      else ('dart.fss.or.kr' in f['namespace']))]
    if not candidates or len({f['value'] for f in candidates}) != 1:
        return None
    return candidates[0]


def verify(data, client, info, download=None):
    from profit_verifier import periods
    if download is None:
        import requests
        def download(receipt, code):
            response = requests.get('https://opendart.fss.or.kr/api/fnlttXbrl.xml',
                                    params={'crtfc_key': client.dart_key, 'rcept_no': receipt, 'reprt_code': code}, timeout=(10, 60))
            response.raise_for_status()
            return response.content
    identifiers = {re.sub(r'\D', '', str(v)) for v in
                   (data['corp'], info.get('jurir_no', ''), info.get('bizr_no', '')) if v}
    latest = data['used'][0]
    filing = latest['filing']
    evidence, issues = [], []
    try:
        facts = collect(download(filing['rcept_no'], latest['rows']['매출']['reprt_code']), identifiers)
    except Exception:
        return {'verified': False, 'evidence': [], 'issues': ['XBRL 원본 수신·해석 실패 또는 원본 비공개. 원문 확인 필요']}
    for section, index in (('cumulative', 0), ('quarterly', 1)):
        for kind, row in latest['rows'].items():
            for i, year in enumerate((data['year'], data['year']-1)):
                period = periods(year, data['quarter'])[index]
                start, end = period.split(' ~ ')
                found = exact(facts, row['account_id'], start, end, data['currency'])
                if found is None and section == 'quarterly' and data['quarter'] > 1:
                    # Only subtract contexts inside the SAME final filing: no mixed correction vintages.
                    cum_start, cum_end = periods(year, data['quarter'])[0].split(' ~ ')
                    prior_start, prior_end = periods(year, data['quarter']-1)[0].split(' ~ ')
                    total = exact(facts, row['account_id'], cum_start, cum_end, data['currency'])
                    prior = exact(facts, row['account_id'], prior_start, prior_end, data['currency'])
                    if total and prior:
                        found = {**total, 'start': start, 'value': total['value']-prior['value'],
                                 'derivation': f"{total['value']} − ({prior['value']})",
                                 'source_contexts': [total, prior]}
                original = data[section][kind][i]
                # Prefer a direct 3-month XBRL fact to cross-filing subtraction.
                if found and original is None:
                    values = list(data[section][kind]); values[i] = found['value']
                    data[section][kind] = tuple(values)
                    original = found['value']
                if not found or found['value'] != original:
                    issues.append(f'{section} · {kind} · {year}: 실제 기간/CFS/통화/금액 원본 일치 미확인')
                else:
                    evidence.append({**found, '항목': kind, '구분': section, 'receipt': filing['rcept_no'],
                                     '비교': '당기' if i == 0 else '전년', 'API/도출값 일치': True})
    return {'verified': not issues and len(evidence) == 8, 'evidence': evidence, 'issues': issues,
            'correction': filing['report_nm'], 'receipt': filing['rcept_no'],
            'method': '최종 정기공시 접수번호 일치 + 동일 XBRL 원본의 CFS 당기/전년 실제 기간·통화·금액 대조'}
