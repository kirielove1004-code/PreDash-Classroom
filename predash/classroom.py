"""Classroom credentials are held only in the current Streamlit session."""
import streamlit as st
from predash.kiwoom import Kiwoom, BrokerError


def account_settings(mode=None):
    settings = st.session_state.get('classroom_credentials', {})
    selected = mode or settings.get('mode', 'demo')
    if selected != settings.get('mode'):
        return dict(mode=selected, key='', secret='', cano='', product='')
    return dict(mode=selected, **{k: settings.get(k, '') for k in ('key','secret','cano','product')})


def connection_form():
    if st.session_state.pop('classroom_clear_inputs', False):
        for key in ('class_key','class_secret'):
            st.session_state.pop(key, None)
    st.subheader('내 증권사 계좌 연결')
    st.caption('키움증권 REST API App Key·App Secret을 입력하세요. 현재 접속 세션에서만 사용합니다.')
    if st.session_state.get('classroom_credentials'):
        st.success('계좌 연결됨 · ' + ('모의투자' if account_settings()['mode']=='demo' else '실전 조회'))
        if st.button('계좌 연결 해제'):
            authorized = st.session_state.get('authorized')
            st.session_state.clear()
            if authorized: st.session_state.authorized = True
            st.rerun()
        return
    with st.form('classroom_connection'):
        mode = st.radio('투자 환경', ['모의투자','실전 조회'], horizontal=True)
        key = st.text_input('App Key', type='password', key='class_key')
        secret = st.text_input('App Secret', type='password', key='class_secret')
        submitted = st.form_submit_button('연결 확인', type='primary', use_container_width=True)
    if submitted:
        settings = dict(mode='demo' if mode=='모의투자' else 'real',key=key.strip(),secret=secret.strip(),cano='',product='')
        try:
            client = Kiwoom(settings=settings)
            with st.spinner('잔고 조회 권한을 확인합니다…'):
                client.balance()
            st.session_state.classroom_credentials = settings
            st.session_state['_kiwoom_client_demo' if settings['mode']=='demo' else '_kiwoom_client'] = client
            st.session_state.classroom_clear_inputs = True
            st.rerun()
        except BrokerError as error:
            st.error(str(error))
    st.info('연결 해제와 로그아웃은 키·잔고·접속 중 실습 기록을 지웁니다. 필요한 기록은 먼저 백업하세요.')
