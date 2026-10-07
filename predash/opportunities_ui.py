"""Private investment candidate workspace. Licensed personal use; no redistribution."""
import csv
import io
import json
import os
import re
from datetime import date
import streamlit as st
import streamlit.components.v1 as components
from predash.opportunities import (SOURCE,SCORE_LIMITS,FACT_LABELS,ResearchError,call_gemini,
    discovery_prompt,discovery_candidates,stock_prompt,normalize_stock,table_rows,
    export_records,restore_records,today_kst,MAX_RECORDS)
from predash.official import DataError


def observed_snapshot(provider,code,asof):
    result={}
    if provider.price_key:
        try:
            rows=provider.price_history(code,asof)
            rows=[r for r in rows if str(r.get('srtnCd','')).removeprefix('A').zfill(6)==code
                  and re.fullmatch(r'[0-9]{8}',str(r.get('basDt','')))]
            if rows:
                latest=max(rows,key=lambda r:r['basDt']);d=date.fromisoformat(latest['basDt'][:4]+'-'+latest['basDt'][4:6]+'-'+latest['basDt'][6:])
                result['price']={'value':int(str(latest['clpr']).replace(',','')),'asof':d.isoformat(),
                                 'source':'https://www.data.go.kr/data/15094808/openapi.do'}
        except (DataError,KeyError,TypeError,ValueError):result['price_error']='공식 시세 조회 실패'
    if provider.dart_key:
        try:
            m=provider.latest_period_metrics(code,asof)
            if m:result['financials']={k:v for k,v in m.items() if k in
                ('year','quarter','basis','revenue','profit','revenue_growth_pct','margin_pct','growth_pct','receipt','source','url')}
        except DataError:result['financial_error']='공식 재무 조회 실패'
    return result


def render_sources(packet):
    # Provider Search Suggestions are displayed in an isolated component.
    if packet.get('search_html'):
        components.html(packet['search_html'],height=160,scrolling=True)
    sources=packet.get('sources') or []
    if sources:
        st.dataframe([{'자료':s.get('title','출처'),'URL':s['url']} for s in sources],hide_index=True,
            column_config={'URL':st.column_config.LinkColumn('원문')},use_container_width=True)


def render_opportunities(provider,password):
    st.title('투자 후보 · 가치 분석표')
    st.caption('시장 → 섹터 → 기업 · PlanX 13번 자동화 스크립트를 개인 분석용으로 변환')
    if not password:
        st.warning('이 탭은 개인용 자료입니다. APP_PASSWORD를 설정하고 앱·저장소를 비공개로 운영하세요.')
        return
    st.caption('사용 허락 범위 내 개인 이용 · 원문 및 파생 분석 기준의 무단 복제·제3자 재배포 금지')
    st.info('점수는 검색 자료를 근거로 한 AI 해석입니다. 출처 연결은 사실의 독립 검증을 뜻하지 않습니다. 자료가 부족하면 총점·등급을 보류합니다.')
    records=st.session_state.setdefault('opportunity_records',[])
    for msg in st.session_state.pop('opportunity_messages',[]):st.write(msg)
    with st.expander('분석 연결',expanded=not records):
        key=st.text_input('Gemini API 키',type='password',key='opportunity_api_key',
                          help='현재 세션에서만 사용합니다. 영구 설정은 Streamlit Secrets의 GEMINI_API_KEY를 사용하세요.')
        try:saved_key=str(st.secrets.get('GEMINI_API_KEY',''));saved_model=str(st.secrets.get('GEMINI_MODEL','gemini-2.5-flash'))
        except FileNotFoundError:saved_key='';saved_model='gemini-2.5-flash'
        key=key or saved_key or os.getenv('GEMINI_API_KEY','')
        model=st.text_input('Gemini 모델',value=saved_model,key='opportunity_model')
        st.caption('Google Search 지원 모델을 사용하세요. 버튼을 누를 때만 API를 호출합니다. 후보 발굴 1회 + 선택 종목당 1회 분석이며 제공사의 사용량 요금이 적용될 수 있습니다.')
    discover,analyze,backups=st.tabs(['1  섹터에서 후보 발굴','2  종목 분석 실행','3  분석 보관'])
    with discover:
        sector=st.text_input('관심 섹터 또는 투자 조건',value='전력기기 · 수출 성장 · 업종 대비 가치',max_chars=200)
        count=st.slider('발굴할 후보 수',3,10,5)
        if st.button('섹터 후보 발굴',type='primary',disabled=not key):
            try:
                with st.spinner('최신 시장·섹터 자료와 후보 종목을 검색합니다…'):
                    packet=call_gemini(key,model,discovery_prompt(sector,count,today_kst()))
                    candidates=discovery_candidates(packet,count)
                st.session_state.opportunity_discovery={'packet':packet,'candidates':candidates,'asof':today_kst().isoformat()}
            except ResearchError as exc:st.error(str(exc))
        discovery=st.session_state.get('opportunity_discovery')
        if discovery:
            st.caption('발굴 기준일 '+discovery['asof'])
            st.write(discovery['packet']['data'].get('market',''));st.write(discovery['packet']['data'].get('sector',''))
            if not discovery['candidates']:st.warning('출처가 연결된 후보를 확보하지 못했습니다. 조건을 바꾸거나 다시 실행하세요.')
            else:st.dataframe([{'코드':c['code'],'종목':c.get('name',''),'업종':c.get('sector',''),
                '발굴 이유':c.get('catalyst',''),'위험':c.get('risk',''),'근거':c.get('evidence','')}
                for c in discovery['candidates']],hide_index=True,use_container_width=True)
            with st.expander('후보 발굴 출처'):render_sources(discovery['packet'])
    with analyze:
        names=st.session_state.get('watch_names',{})
        candidates={c:c for c in st.session_state.get('watch_codes',[])}
        candidates.update({c['code']:c.get('name',c['code']) for c in (st.session_state.get('opportunity_discovery') or {}).get('candidates',[])})
        candidates.update({c:names[c] for c in candidates if names.get(c)})
        selected=st.multiselect('발굴 후보·관심종목에서 선택',list(candidates),format_func=lambda c:f'{candidates[c]} · {c}')
        manual=st.text_input('추가할 종목코드',placeholder='267260, 010120, 298040',max_chars=150)
        official=st.checkbox('기존 공식 API 시세·공시도 함께 조회',value=False,
            help='DART 및 공공데이터포털 키가 있을 때 조회합니다. 종목 수가 많으면 시간이 걸릴 수 있습니다.')
        if st.button('선택 종목 가치 분석',type='primary',disabled=not key):
            tokens=[t for t in re.split(r'[,\s]+',manual.strip()) if t]
            if any(not re.fullmatch(r'[0-9]{6}',c) for c in tokens):st.error('추가 종목코드는 숫자 6자리로 입력하세요.')
            else:
                codes=list(dict.fromkeys(selected+tokens))
                if not 1<=len(codes)<=10:st.warning('한 번에 1~10개 종목을 선택하세요.')
                else:
                    asof=today_kst();progress=st.progress(0);success=0;messages=[]
                    for i,code in enumerate(codes):
                        try:
                            with st.spinner(f'{code} · {i+1}/{len(codes)} 분석 중…'):
                                observed=observed_snapshot(provider,code,asof) if official else {}
                                packet=call_gemini(key,model,stock_prompt(code,candidates.get(code,code),asof,observed))
                                record=normalize_stock(packet,code,asof,observed)
                            records=[r for r in records if r['code']!=code]+[record]
                            records=records[-MAX_RECORDS:]
                            st.session_state.opportunity_records=records
                            success+=1
                        except ResearchError as exc:
                            messages.append(f'{code}: {exc}');st.error(messages[-1])
                        progress.progress((i+1)/len(codes))
                    if success:
                        messages.append(f'{success}개 종목 분석을 저장했습니다. 출처 부족 항목은 보류 표시됩니다.')
                        st.session_state.opportunity_messages=messages
                        st.rerun()
    with backups:
        st.caption('최근 분석 20개는 이 브라우저에 복원됩니다. 브라우저 데이터 삭제·기기 변경에 대비해 개인용 백업을 내려받아 보관하세요. API 키는 백업에 포함하지 않습니다.')
        if records:st.download_button('개인용 분석 백업(JSON)',export_records(records),'private-investment-analysis.json','application/json')
        upload=st.file_uploader('내 분석 백업 복원',type=['json'])
        if upload and st.button('분석 백업 불러오기'):
            try:
                records=restore_records(upload.getvalue().decode('utf-8'))
                st.session_state.opportunity_records=records
                st.rerun()
            except (UnicodeError,ResearchError) as exc:st.error(str(exc))
    st.subheader('투자 후보 비교표')
    if not records:
        st.info('섹터 후보를 발굴하거나 관심종목을 선택해 분석을 실행하세요. 실행 전에는 가상 점수나 샘플 종목을 표시하지 않습니다.')
        st.dataframe([{'종목':'분석 대기','AI 점수/120':None,'등급':'보류','검토 상태':'실행 전'}],hide_index=True,use_container_width=True)
        return
    a,b,c=st.columns(3)
    a.metric('분석 종목',len(records));b.metric('우선 검토',sum(r['status']=='우선 검토' for r in records));c.metric('자료 보완',sum(r['total'] is None for r in records))
    f1,f2,f3=st.columns(3)
    with f1:mode=st.selectbox('검토 상태',['전체','우선 검토','관찰','신중 검토','자료 보완'])
    with f2:minimum=st.slider('최소 AI 점수',0,120,0,5)
    with f3:query=st.text_input('종목·업종 검색',max_chars=100)
    filtered=[r for r in records if (mode=='전체' or r['status']==mode) and
              (not minimum or (r['total'] is not None and r['total']>=minimum)) and
              (not query or query.lower() in (r['name']+r['code']+r['sector']).lower())]
    rows=table_rows(filtered)
    st.caption('S ≥100 · A ≥85 · B ≥70 · C ≥55 · D <55 / 총점은 8영역 근거와 최근 가격이 있을 때만 표시 · 과거 분석은 기준일을 확인하세요.')
    st.dataframe(rows,hide_index=True,use_container_width=True,column_config={
        '출처':st.column_config.LinkColumn('검색 출처'),
        'AI 점수/120':st.column_config.ProgressColumn('AI 점수/120',min_value=0,max_value=120,format='%d'),
        '목표가 괴리율(%)':st.column_config.NumberColumn(format='%.1f')})
    if rows:
        buf=io.StringIO();writer=csv.DictWriter(buf,fieldnames=list(rows[0]));writer.writeheader();writer.writerows({k:("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v) for k,v in r.items()} for r in rows)
        st.download_button('내 비교표 CSV 저장',buf.getvalue().encode('utf-8-sig'),'private-investment-table.csv','text/csv')
    selected_record=st.selectbox('상세 분석',records,format_func=lambda r:f"{r['name']} · {r['code']} · {r['asof']}")
    st.write('성장 촉매: '+selected_record['catalyst']);st.write('수급: '+selected_record['flow'])
    st.write('위험: '+' / '.join(selected_record['risks']));st.write(selected_record['verdict'])
    st.dataframe([{'영역':s['area'],'AI 점수':s['score'],'배점':s['max'],'근거 기준일':s['asof'],
                  '근거':s['evidence'],'출처':(s['sources'] or [{}])[0].get('url','')}
                 for s in selected_record['scores']],hide_index=True,use_container_width=True,
                 column_config={'출처':st.column_config.LinkColumn('근거 원문')})
    with st.expander('수치별 기준일·출처'):
        st.dataframe([{'항목':FACT_LABELS[k],'값':f['value'],'기준일':f['asof'],'구분':f['origin'],
                       '근거':f['evidence'],'출처':(f['sources'] or [{}])[0].get('url','')}
                     for k,f in selected_record['facts'].items()],hide_index=True,use_container_width=True,
                     column_config={'출처':st.column_config.LinkColumn('원문')})
        if selected_record['observed']:st.json(selected_record['observed'])
    with st.expander('전체 검색 출처'):render_sources(selected_record['packet'])
