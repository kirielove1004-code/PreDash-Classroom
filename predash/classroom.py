"""Classroom credentials are held only in the current Streamlit session."""
import streamlit as st
from predash.kiwoom import Kiwoom, BrokerError


def account_settings(mode=None):
    settings = st.session_state.get('classroom_credentials', {})
    selected = mode or settings.get('mode', 'real')
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
                # Kiwoom's official SDK classifies 8001 as invalid credentials.
                # A very common cause is using a demo key against the real endpoint (or vice versa).
                if '8001' in message or '8002' in message or '8011' in message or '8012' in message:
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
    st.info('연결 해제와 로그아웃은 키·잔고·접속 중 실습 기록을 지웁니다. 필요한 기록은 먼저 백업하세요.')
