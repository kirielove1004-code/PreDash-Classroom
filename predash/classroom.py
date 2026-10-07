"""Classroom credentials are held only in the current Streamlit session."""
import os
import requests
import streamlit as st
from predash.kiwoom import Kiwoom, BrokerError


def account_settings(mode=None):
    """Prefer session credentials, then persistent Streamlit Secrets."""
    session = st.session_state.get('classroom_credentials', {})
    selected = mode or session.get('mode', 'real')
    if session and selected == session.get('mode'):
        return dict(mode=selected, **{k: session.get(k, '') for k in ('key','secret','cano','product')})
    prefix='KIWOOM_DEMO_' if selected=='demo' else 'KIWOOM_REAL_'
    key=os.getenv(prefix+'APP_KEY','').strip()
    secret=os.getenv(prefix+'APP_SECRET','').strip()
    return dict(mode=selected,key=key,secret=secret,cano='',product='')


def credential_source(mode=None):
    selected=mode or st.session_state.get('classroom_credentials',{}).get('mode','real')
    session=st.session_state.get('classroom_credentials',{})
    if session and session.get('mode')==selected and session.get('key') and session.get('secret'):
        return '현재 세션'
    settings=account_settings(selected)
    if settings.get('key') and settings.get('secret'):
        return 'Streamlit Secrets'
    return '미연결'


def connection_form():
    if st.session_state.pop('classroom_clear_inputs', False):
        for key in ('class_key','class_secret'):
            st.session_state.pop(key, None)
    st.subheader('내 증권사 계좌 연결')
    st.caption('키움증권 REST API App Key·App Secret을 연결합니다. 장기 사용은 Streamlit Secrets, 일회성 테스트는 현재 세션 입력을 사용합니다.')
    saved_real=account_settings('real')
    saved_demo=account_settings('demo')

    with st.expander('키움 IP 등록 도움',expanded=False):
        st.write('키움 8050 오류는 App Key/Secret보다 먼저 API 요청을 보내는 서버 IP가 등록되어야 한다는 뜻입니다.')
        if st.button('현재 Streamlit 서버 공인 IP 확인',use_container_width=True,key='show_kiwoom_server_ip'):
            try:
                ip_resp=requests.get('https://api.ipify.org',params={'format':'json'},timeout=(4,8))
                current_ip=str(ip_resp.json().get('ip','')).strip() if ip_resp.ok else ''
            except (requests.RequestException,ValueError):
                current_ip=''
            if current_ip:
                st.session_state.kiwoom_server_ip=current_ip
            else:
                st.error('현재 서버 공인 IP를 확인하지 못했습니다. 잠시 후 다시 시도하세요.')
        current_ip=st.session_state.get('kiwoom_server_ip','')
        if current_ip:
            st.write('키움에 우선 등록할 현재 서버 공인 IP')
            st.code(current_ip,language=None)
            st.caption('키움 REST API → 계좌 App Key 관리 → IP 등록에서 이 IP를 추가하세요. 등록 후 같은 화면에서 Secrets 연결 실제 확인을 다시 누르세요.')
        st.warning('Streamlit Community Cloud는 여러 공인 IP를 사용할 수 있고 목록은 변경될 수 있습니다. 현재 IP 1개 등록은 빠른 해결책이지만 재배포/서버 이동 후 다시 8050이 날 수 있습니다.')
        st.link_button('키움 REST API · App Key/IP 관리','https://openapi.kiwoom.com/',use_container_width=True)
    persistent_mode='real' if saved_real.get('key') and saved_real.get('secret') else 'demo' if saved_demo.get('key') and saved_demo.get('secret') else None
    if st.session_state.get('classroom_credentials') or persistent_mode:
        active=st.session_state.get('classroom_credentials',{}).get('mode') or persistent_mode
        source=credential_source(active)
        st.success('계좌 연결 준비됨 · ' + ('모의투자' if active=='demo' else '실전 조회') + ' · ' + source)
        if source=='Streamlit Secrets':
            st.caption('Secrets 값은 화면에 표시하지 않습니다. 아래 버튼으로 실제 키움 토큰·잔고 조회까지 확인할 수 있습니다.')
            if st.button('Secrets 연결 실제 확인',type='primary',use_container_width=True):
                try:
                    settings=account_settings(active)
                    client=Kiwoom(settings=settings)
                    with st.spinner('키움 토큰 발급과 잔고 조회를 확인합니다…'):
                        client.authorize()
                        client.balance()
                    st.session_state['_kiwoom_client_demo' if active=='demo' else '_kiwoom_client']=client
                    st.success('키움증권 연결 정상 · 계좌·보유종목·체결내역·수급 조회를 사용할 수 있습니다.')
                except BrokerError as error:
                    message=str(error)
                    if '8050' in message or '8040' in message or '8010' in message or '8103' in message:
                        st.error('키움 단말기/IP 인증이 필요합니다 · '+message)
                        try:
                            ip_resp=requests.get('https://api.ipify.org',params={'format':'json'},timeout=(4,8))
                            current_ip=str(ip_resp.json().get('ip','')).strip() if ip_resp.ok else ''
                        except (requests.RequestException,ValueError):
                            current_ip=''
                        if current_ip:
                            st.write('키움에 등록할 현재 Streamlit 서버 공인 IP')
                            st.code(current_ip,language=None)
                        st.caption('키움 REST API 홈페이지 → API 사용신청/단말기(IP) 등록에서 위 서버 IP를 등록한 뒤 다시 확인하세요.')
                        st.link_button('키움 REST API · IP 등록/사용신청','https://openapi.kiwoom.com/',use_container_width=True)
                    else:
                        st.error(message)
                        st.caption('8001 계열 오류면 실전/모의 키 구분과 App Key·App Secret 쌍을 다시 확인하세요.')
            st.info('Secrets 연결을 해제하려면 Streamlit → Manage app → Settings → Secrets에서 해당 KIWOOM_* 값을 제거해야 합니다.')
        else:
            if st.button('계좌 연결 해제'):
                authorized = st.session_state.get('authorized')
                st.session_state.clear()
                if authorized: st.session_state.authorized = True
                st.rerun()
        return
    with st.form('classroom_connection'):
        mode = st.radio('투자 환경', ['실전 조회','모의투자'], horizontal=True)
        key = st.text_input('App Key', type='password', key='class_key')
        secret = st.text_input('App Secret', type='password', key='class_secret')
        submitted = st.form_submit_button('연결 확인', type='primary', use_container_width=True)
    if submitted:
        settings = dict(mode='real' if mode=='실전 조회' else 'demo',key=key.strip(),secret=secret.strip(),cano='',product='')
        if not settings['key'] or not settings['secret']:
            st.error('App Key와 App Secret을 모두 입력하세요.')
        else:
            try:
                client = Kiwoom(settings=settings)
                with st.spinner('키움 인증과 잔고 조회 권한을 확인합니다…'):
                    client.authorize()
                    client.balance()
                st.session_state.classroom_credentials = settings
                st.session_state['_kiwoom_client_demo' if settings['mode']=='demo' else '_kiwoom_client'] = client
                st.session_state.classroom_clear_inputs = True
                st.rerun()
            except BrokerError as error:
                message=str(error)
                if '8050' in message or '8040' in message or '8010' in message or '8103' in message:
                    st.error('키움 단말기/IP 인증이 필요합니다 · '+message)
                    st.info('등록해야 하는 IP는 지금 이 Streamlit 서버가 키움 API에 접속할 때 사용하는 공인 IP입니다. 집/회사 PC의 IP가 아닐 수 있습니다.')
                    try:
                        ip_resp=requests.get('https://api.ipify.org',params={'format':'json'},timeout=(4,8))
                        current_ip=str(ip_resp.json().get('ip','')).strip() if ip_resp.ok else ''
                    except (requests.RequestException,ValueError):
                        current_ip=''
                    if current_ip:
                        st.code(current_ip,language=None)
                        st.caption('위 IP를 키움 REST API 홈페이지의 API 사용신청/단말기(IP) 등록 화면에 등록한 뒤 다시 연결 확인을 누르세요.')
                    else:
                        st.caption('현재 Streamlit 서버의 공인 IP를 자동 확인하지 못했습니다. 키움 REST API 홈페이지의 단말기/IP 등록 안내를 확인하세요.')
                    st.link_button('키움 REST API · IP 등록/사용신청','https://openapi.kiwoom.com/',use_container_width=True)
                    st.warning('Streamlit 서버의 외부 IP가 바뀌면 키움에서 다시 IP 등록이 필요할 수 있습니다. 8050 오류는 App Key/Secret 오타가 아니라 단말기/IP 인증 단계의 오류입니다.')
                # Kiwoom's official SDK classifies 8001/8002/8011/8012 as invalid credentials.
                elif '8001' in message or '8002' in message or '8011' in message or '8012' in message:
                    other_mode='demo' if settings['mode']=='real' else 'real'
                    other_label='모의투자' if other_mode=='demo' else '실전 조회'
                    try:
                        alt_settings={**settings,'mode':other_mode}
                        alt_client=Kiwoom(settings=alt_settings)
                        with st.spinner(f'{other_label} 키인지 자동 확인합니다…'):
                            alt_client.authorize()
                            alt_client.balance()
                        st.session_state.classroom_credentials = alt_settings
                        st.session_state['_kiwoom_client_demo' if other_mode=='demo' else '_kiwoom_client'] = alt_client
                        st.session_state.classroom_clear_inputs = True
                        st.success(f'입력한 키는 {other_label}용으로 확인되어 환경을 자동으로 맞췄습니다.')
                        st.rerun()
                    except BrokerError:
                        st.error('키움 인증 실패 · 선택한 환경과 반대 환경을 모두 확인했지만 인증되지 않았습니다. App Key/App Secret 쌍이 정확한지, 키움 REST API에서 해당 키가 활성 상태인지 확인하세요.')
                        st.caption('키움 공식 오류 분류상 8001/8002/8011/8012는 자격증명 오류입니다. 실전 키와 모의투자 키는 서로 호환되지 않습니다.')
                else:
                    st.error(message)
    st.info('권장: 장기 사용은 Streamlit Secrets에 키움 실전/모의 키를 저장하세요. 세션 입력값은 로그아웃·재접속 시 사라집니다.')
