"""Private Supabase persistence for user-authored workspace data only."""
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .paper import replay
from .watchlist import clean_codes, clean_names


class WorkspaceError(RuntimeError):
    pass


NOTE_FIELDS = ("sector", "hs", "path", "basis", "unknown", "stop_rule")


def normalize(payload):
    if not isinstance(payload, dict):
        return {"version": 1, "watch_codes": [], "watch_names": {}, "industry_notes": {}}
    codes = clean_codes(payload.get("watch_codes", []))
    notes = {}
    raw_notes = payload.get("industry_notes", {})
    if isinstance(raw_notes, dict):
        for code in codes:
            item = raw_notes.get(code)
            if isinstance(item, dict):
                notes[code] = {key: str(item.get(key, ""))[:2000] for key in NOTE_FIELDS}
    result = {
        "version": 1,
        "watch_codes": codes,
        "watch_names": clean_names(payload.get("watch_names", {}), codes),
        "industry_notes": notes,
    }
    account = payload.get("paper_account")
    if isinstance(account, dict):
        replay(account)
        result["paper_account"] = account
    page = payload.get("last_page")
    if page in ("오늘의 점검", "관심종목", "투자 근거", "내 계좌", "모의투자", "매매 연습", "매매 습관", "연결 설정"):
        result["last_page"] = page
    encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 1_000_000:
        raise WorkspaceError("저장할 작업 내용이 1MB를 초과했습니다.")
    return result


def capture(session):
    codes = clean_codes(session.get("watch_codes", []))
    payload = {
        "version": 1,
        "watch_codes": codes,
        "watch_names": session.get("watch_names", {}),
        "industry_notes": {code: session.get("industry_note_" + code, {}) for code in codes},
        "paper_account": session.get("paper_account"),
        "last_page": session.get("navigation"),
    }
    return normalize(payload)


def restore(session, payload):
    data = normalize(payload)
    session["watch_codes"] = data["watch_codes"]
    session["watch_names"] = data["watch_names"]
    for code, note in data["industry_notes"].items():
        session["industry_note_" + code] = note
    if "paper_account" in data:
        session["paper_account"] = data["paper_account"]
    if data.get("last_page"):
        session["navigation"] = data["last_page"]
    return data


class WorkspaceStore:
    def __init__(self, url="", key=""):
        self.url = str(url or "").rstrip("/")
        self.key = str(key or "").strip()
        if bool(self.url) != bool(self.key):
            raise WorkspaceError("SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY를 모두 설정하세요.")
        if self.url and not self.url.startswith("https://"):
            raise WorkspaceError("SUPABASE_URL은 HTTPS 주소여야 합니다.")

    @property
    def configured(self):
        return bool(self.url and self.key)

    def _headers(self, prefer=None):
        result = {"apikey": self.key, "Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        if prefer:
            result["Prefer"] = prefer
        return result

    def load(self):
        if not self.configured:
            return normalize({})
        try:
            response = requests.get(
                self.url + "/rest/v1/predash_workspace",
                headers=self._headers(), params={"id": "eq.personal", "select": "payload"}, timeout=15,
            )
            response.raise_for_status()
            rows = response.json()
            return normalize(rows[0]["payload"] if rows else {})
        except (requests.RequestException, ValueError, KeyError, TypeError):
            raise WorkspaceError("저장된 작업을 불러오지 못했습니다. Supabase 설정과 테이블을 확인하세요.") from None

    def save(self, payload):
        if not self.configured:
            return False
        data = normalize(payload)
        try:
            response = requests.post(
                self.url + "/rest/v1/predash_workspace",
                headers=self._headers("resolution=merge-duplicates,return=minimal"),
                params={"on_conflict": "id"},
                json={"id": "personal", "payload": data,
                      "updated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat()}, timeout=15,
            )
            response.raise_for_status()
            return True
        except requests.RequestException:
            raise WorkspaceError("작업을 저장하지 못했습니다. Supabase 연결 상태를 확인하세요.") from None
