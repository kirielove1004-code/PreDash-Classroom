# PreDash Classroom · 수강생 투자 대시보드

선생님의 PreDash와 분리한 수업용 코드입니다. 개인 계좌를 조회하고 시장·기업·수급·차트를 보면서 나만의 투자 화면을 실습합니다. 실제 주문 전송 기능은 없습니다.

## 수강생 시작 순서

1. 이 저장소의 Fork 버튼 → 본인 계정에 복사합니다.
2. Streamlit Community Cloud에서 본인 Fork의 main / app.py를 배포합니다.
3. 앱 Settings → Secrets에 APP_PASSWORD를 설정합니다. 기업 분석용 DART·공공데이터 키는 .streamlit.example.toml의 빈 항목을 본인 키로 설정합니다.
4. Supabase SQL Editor에서 `supabase-workspace.sql`을 한 번 실행하고 Secrets에 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`를 설정하면 작업 내용이 자동 저장됩니다.
5. 앱 로그인 → 연결 설정 → 모의투자 선택 → 본인 App Key·App Secret·계좌번호 입력 → 연결 확인.
6. 관심종목·투자 근거·대시보드를 자신의 기획에 맞춰 수정합니다.

관심종목, 산업·기업 연결 메모, 모의투자 기록과 마지막 메뉴는 Supabase에 자동 저장됩니다. 증권사 키·계좌번호·실계좌 잔고와 조회 캐시는 영구 저장하지 않으며 연결 해제·로그아웃 시 세션에서 제거합니다. Supabase 서비스 역할 키는 반드시 Streamlit Secrets에만 넣고 GitHub 코드나 게시판에 올리지 마세요.

## 교육과 소통

- 교육자료: https://stock-dash-11a.streamlit.app/
- 선생님 공지·수강생 질문·아이디어: https://etf2x.com/learn/live

게시판에는 키, 계좌번호, 잔고 원본을 올리지 않습니다. 아이디어와 개인정보를 가린 화면을 공유합니다.

## 업데이트

선생님 배포본 업데이트는 본인 Fork의 Sync fork로 반영합니다. 본인 변경과 충돌하면 덮어쓰기 전에 비교하세요. 이 저장소는 원본 PreDash의 046f13530430a1e2c9415775bf51b7fdfdc49d97을 기준으로 새 이력으로 배포합니다.

## 실습 순서

계좌 연결 → 시장 환경(VIX·지수) → 주도 섹터·종목 → 실적·가치·수급·차트 → 나의 투자판단 화면. 연결되지 않은 기능과 자료 부족 상태는 해당 화면에서 구분합니다. 가상 데이터는 화면·로직 실습용이며 투자 판단 근거가 아닙니다.
