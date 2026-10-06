# PreDash Classroom · 수강생 투자 대시보드

선생님의 PreDash와 분리한 수업용 코드입니다. 개인 계좌를 조회하고 시장·기업·수급·차트를 보면서 나만의 투자 화면을 실습합니다. 실제 주문 전송 기능은 없습니다.

## 수강생 시작 순서

1. 이 저장소의 Fork 버튼 → 본인 계정에 복사합니다.
2. Streamlit Community Cloud에서 본인 Fork의 main / app.py를 배포합니다.
3. 앱 Settings → Secrets에 APP_PASSWORD를 설정합니다. 기업 분석용 DART·공공데이터 키는 .streamlit.example.toml의 빈 항목을 본인 키로 설정합니다.
4. 앱 로그인 → 연결 설정 → 실전 조회 또는 모의투자 선택 → 키움증권 REST API App Key·App Secret 입력 → 연결 확인.
5. 관심종목·투자 근거·대시보드를 자신의 기획에 맞춰 수정합니다.

키움증권 App Key·App Secret은 GitHub 코드에 저장하지 않습니다. 장기 사용은 Streamlit의 비공개 Secrets에 `KIWOOM_REAL_APP_KEY` / `KIWOOM_REAL_APP_SECRET` 또는 모의투자용 `KIWOOM_DEMO_APP_KEY` / `KIWOOM_DEMO_APP_SECRET`으로 저장할 수 있습니다. 일회성 테스트는 앱 세션 입력을 사용할 수 있습니다. Secrets 원문은 앱 화면에 표시하지 않습니다.

## 교육과 소통

- 교육자료: https://stock-dash-11a.streamlit.app/
- 선생님 공지·수강생 질문·아이디어: https://etf2x.com/learn/live

게시판에는 키, 계좌번호, 잔고 원본을 올리지 않습니다. 아이디어와 개인정보를 가린 화면을 공유합니다.

## 업데이트

선생님 배포본 업데이트는 본인 Fork의 Sync fork로 반영합니다. 본인 변경과 충돌하면 덮어쓰기 전에 비교하세요. 이 저장소는 원본 PreDash의 046f13530430a1e2c9415775bf51b7fdfdc49d97을 기준으로 새 이력으로 배포합니다.

## 실습 순서

계좌 연결 → 시장 환경(VIX·지수) → 주도 섹터·종목 → 실적·가치·수급·차트 → 나의 투자판단 화면. 연결되지 않은 기능과 자료 부족 상태는 해당 화면에서 구분합니다. 가상 데이터는 화면·로직 실습용이며 투자 판단 근거가 아닙니다.


## 키움증권 REST API

계좌·보유종목·체결내역·외국인/기관 수급·국내 지수 일별 흐름은 키움증권 REST API의 조회 전용 TR을 사용합니다. 주문 전송 기능은 구현하지 않습니다. App Key와 App Secret에 연결된 계좌는 키움 REST API 포털에서 관리합니다.
