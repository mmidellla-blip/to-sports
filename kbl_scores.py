"""
KBL 정규시즌 경기 결과(전반/최종 점수) 자동 수집기

사용법
  1) 최종 점수만 먼저 받기 (바로 동작)
       python kbl_scores.py --from 20251001 --to 20260415
  2) 쿼터 점수 엔드포인트 찾기 (경기 1개로 테스트)
       python kbl_scores.py --probe S47G01N1
  3) (해결됨) QUARTER_URL = /match/{gmkey} 로 전반 점수까지 자동 수집
       -> home_half, away_half 칸이 자동으로 채워짐

필요 패키지: pip install requests truststore
"""
import argparse
import csv
import json
import re
import sys
import time
from datetime import date, datetime, timedelta

import requests

try:
    # KBL API 서버도 중간 인증서를 안 보내서, 윈도우 인증서 저장소를 쓰게 해요 (kbo_scores.py와 같은 이유)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

BASE = "https://api.kbl.or.kr"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.kbl.or.kr/",
    "Origin": "https://www.kbl.or.kr",
    "X-Requested-With": "XMLHttpRequest",
    # KBL API 전용 헤더 - 없으면 400 에러
    "channel": "WEB",
    "teamcode": "XX",
    "lang": "ko",
}

# 쿼터 점수 엔드포인트. 응답의 teamrecords.home/away.scoreq1~4 에 쿼터 점수가 있어요.
QUARTER_URL = BASE + "/match/{gmkey}"

# --probe 에서 시험해 볼 후보 주소 (추정값이라 일부만 맞을 수 있음)
PROBE_CANDIDATES = [
    # 프리뷰 주소(/match/getPreviewData/{date}/{gmkey})와 같은 형식의 후보
    "/match/getScoreData/{date}/{gmkey}",
    "/match/getQuarterData/{date}/{gmkey}",
    "/match/getQuarterScoreData/{date}/{gmkey}",
    "/match/getBoxScoreData/{date}/{gmkey}",
    "/match/getBoxscoreData/{date}/{gmkey}",
    "/match/getRecordData/{date}/{gmkey}",
    "/match/getGameRecordData/{date}/{gmkey}",
    "/match/getTeamRecordData/{date}/{gmkey}",
    "/match/getResultData/{date}/{gmkey}",
    "/match/getGameData/{date}/{gmkey}",
    "/match/getGameResultData/{date}/{gmkey}",
    "/match/getSummaryData/{date}/{gmkey}",
    "/match/getScoreBoardData/{date}/{gmkey}",
    "/match/getReviewData/{date}/{gmkey}",
    "/match/getLiveData/{date}/{gmkey}",
    # 하이라이트 주소(/match/highlight/{gmkey}/{date})와 같은 형식의 후보
    "/match/score/{gmkey}/{date}",
    "/match/quarter/{gmkey}/{date}",
    "/match/quarterscore/{gmkey}/{date}",
    "/match/scoreboard/{gmkey}/{date}",
    "/match/boxscore/{gmkey}/{date}",
    "/match/record/{gmkey}/{date}",
    "/match/detail/{gmkey}/{date}",
    "/match/info/{gmkey}/{date}",
    "/match/summary/{gmkey}/{date}",
    "/match/result/{gmkey}/{date}",
    "/match/team/{gmkey}/{date}",
    "/match/teamrecord/{gmkey}/{date}",
    "/match/score/{gmkey}",
    "/match/quarter/{gmkey}",
    "/match/boxscore/{gmkey}",
    "/match/info/{gmkey}",
    "/match/{gmkey}",
    "/match/detail?gmkey={gmkey}",
    "/match/score?gmkey={gmkey}",
    "/match/{gmkey}/score",
    "/match/{gmkey}/quarter",
    "/match/quarter?gmkey={gmkey}",
    "/match/boxscore?gmkey={gmkey}",
    "/match/{gmkey}/boxscore",
    "/record/match/{gmkey}",
    "/match/record?gmkey={gmkey}",
]

REGULAR_SEASON_GAMECODE = "01"   # 정규시즌 (14 = 오픈매치데이 같은 비정규 경기)


def get_json(url, **params):
    r = requests.get(url, params=params or None, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} - {r.url}\n서버 응답: {r.text[:300]}")
    return r.json()


def month_ranges(start, end):
    """API 한 번에 너무 긴 기간을 요청하지 않도록 한 달 단위로 쪼갬."""
    cur = start
    while cur <= end:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield cur, min(end, nxt - timedelta(days=1))
        cur = nxt


def fetch_matches(d_from, d_to):
    games = []
    for a, b in month_ranges(d_from, d_to):
        data = get_json(f"{BASE}/match/list",
                        fromDate=a.strftime("%Y%m%d"),
                        toDate=b.strftime("%Y%m%d"),
                        tcodeList="all")
        games.extend(data if isinstance(data, list) else data.get("list", []))
        time.sleep(0.3)
    return games


# ---------- 쿼터 점수 파싱 ----------
# 응답 구조를 모르기 때문에, 흔한 키 이름 패턴을 재귀적으로 찾아봅니다.
Q_KEY = re.compile(r"^(?:q|qt|quarter|score|scoreq|pt)?_?([1-4])_?(h|a|home|away)$|"
                   r"^(h|a|home|away)_?(?:q|qt|quarter|score)?_?([1-4])$", re.I)


def find_quarters(obj):
    """{'H': [q1..q4], 'A': [q1..q4]} 형태로 반환. 못 찾으면 None."""
    found = {"H": {}, "A": {}}

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                m = Q_KEY.match(str(k))
                if m and isinstance(v, (int, float, str)) and str(v).strip().isdigit():
                    q = m.group(1) or m.group(4)
                    side = (m.group(2) or m.group(3)).lower()[0].upper()
                    found[side][int(q)] = int(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(obj)
    if all(q in found[s] for s in "HA" for q in (1, 2)):
        return {s: [found[s].get(q) for q in (1, 2, 3, 4)] for s in "HA"}
    return None


def fetch_half(gmkey, gdate):
    if not QUARTER_URL:
        return None, None
    try:
        data = get_json(QUARTER_URL.format(gmkey=gmkey, date=gdate))
    except Exception as e:
        print(f"  [쿼터 실패] {gmkey}: {e}", file=sys.stderr)
        return None, None
    tr = data.get("teamrecords") or {}
    try:
        return (int(tr["home"]["scoreq1"]) + int(tr["home"]["scoreq2"]),
                int(tr["away"]["scoreq1"]) + int(tr["away"]["scoreq2"]))
    except (KeyError, TypeError, ValueError):
        pass
    qs = find_quarters(data)
    if not qs:
        print(f"  [쿼터 파싱 실패] {gmkey} - 응답 구조 확인 필요", file=sys.stderr)
        return None, None
    return qs["H"][0] + qs["H"][1], qs["A"][0] + qs["A"][1]


def clean_name(n):
    return (n or "").replace(" ", "")


def run(d_from, d_to, out, include_all):
    games = fetch_matches(d_from, d_to)
    rows = []
    for g in games:
        if not g.get("isEnded"):
            continue
        if not include_all:
            if g.get("gameCode") != REGULAR_SEASON_GAMECODE:
                continue
            # D리그(2군)도 gameCode 가 01 이라 시즌 이름으로 한 번 더 거름 (1군은 "2025-2026" 형식)
            if not re.fullmatch(r"\d{4}-\d{4}", g.get("seasonName1", "")):
                continue
        hh, ah = fetch_half(g["gmkey"], g["gameDate"])
        d = datetime.strptime(g["gameDate"], "%Y%m%d").date()
        rows.append({
            "date": d.isoformat(),
            "season": g.get("seasonName1", "").replace("-20", "-"),
            "gmkey": g["gmkey"],
            "home": clean_name(g.get("tnameH")),
            "away": clean_name(g.get("tnameA")),
            "home_half": hh if hh is not None else "",
            "away_half": ah if ah is not None else "",
            "home_final": g.get("scoreH"),
            "away_final": g.get("scoreA"),
        })
        if QUARTER_URL:
            time.sleep(0.3)

    rows.sort(key=lambda r: (r["date"], r["gmkey"]))
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["date"])
        w.writeheader()
        w.writerows(rows)
    filled = sum(1 for r in rows if r["home_half"] != "")
    print(f"저장 완료: {out}  (경기 {len(rows)}개, 전반 점수 채움 {filled}개)")


def probe(gmkey, gdate):
    print(f"후보 엔드포인트 시험 중: {gmkey} / {gdate}\n")
    for path in PROBE_CANDIDATES:
        url = BASE + path.format(gmkey=gmkey, date=gdate)
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            status = r.status_code
            body = r.text[:300].replace("\n", " ")
            hit = ""
            if status == 200:
                try:
                    if find_quarters(r.json()):
                        hit = "  <== 쿼터 점수 발견!"
                except ValueError:
                    pass
                if not hit and re.search(r"1Q|Q1|1쿼터|1st|쿼터", r.text):
                    hit = "  <== 쿼터 관련 글자 있음 (응답 확인 필요)"
            print(f"[{status}] {url}{hit}\n      {body}\n")
        except Exception as e:
            print(f"[ERR] {url}  {e}\n")
    print("못 찾았다면: kbl.or.kr 에서 경기 상세(박스스코어) 페이지를 열고 "
          "F12 → Network → Fetch/XHR 에서 쿼터 점수가 담긴 요청 주소를 찾아 QUARTER_URL 에 넣어주세요.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="d_from", default="20251001")
    p.add_argument("--to", dest="d_to", default="20260415")
    p.add_argument("--out", default="kbl_results.csv")
    p.add_argument("--all", action="store_true", help="오픈매치 등 비정규 경기도 포함")
    p.add_argument("--probe", metavar="GMKEY", help="쿼터 점수 엔드포인트 탐색")
    p.add_argument("--date", default="20251003", help="--probe 경기 날짜 (YYYYMMDD)")
    a = p.parse_args()

    if a.probe:
        probe(a.probe, a.date)
    else:
        run(datetime.strptime(a.d_from, "%Y%m%d").date(),
            datetime.strptime(a.d_to, "%Y%m%d").date(),
            a.out, a.all)
