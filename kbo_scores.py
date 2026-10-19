"""
KBO 정규시즌 경기 결과 자동 수집기 (야구토토 스페셜 분석용)

사용법
  python kbo_scores.py --from 20260328 --to 20261012        # 기간 수집 → kbo_games.csv
  python kbo_scores.py --season 2025                        # 시즌 전체 (3월~10월)
  python kbo_scores.py --season 2026 --no-innings           # 이닝 점수 없이 빠르게

  python kbo_scores.py --fill-hr                            # 이미 모은 경기에 팀 홈런 수 채우기

경기마다 날짜·구장·홈/원정·선발 투수·5회 점수·최종 점수·이닝별 점수·팀 홈런 수를 저장해요.
이미 kbo_games.csv에 있는 경기는 건너뛰니 매일 다시 돌려도 새 경기만 붙어요.
취소·노게임·진행 중 경기는 저장하지 않아요.

데이터: KBO 홈페이지(koreabaseball.com)가 화면에 쓰는 요청을 그대로 써요.
예의: 요청 사이에 쉬고(기본 0.7초), 개인 학습 용도로만 쓰세요.

필요 패키지: pip install requests truststore
"""
import argparse
import csv
import json
import pathlib
import sys
import time
from datetime import date, datetime, timedelta

import requests

try:
    # KBO 사이트는 중간 인증서를 안 보내서 파이썬 기본 인증서 목록으론 검증이 실패해요.
    # truststore는 윈도우 인증서 저장소(브라우저와 같은 것)를 쓰게 해줘요.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    sys.exit("pip install truststore 를 먼저 실행하세요 (KBO 사이트 인증서 검증용)")

BASE = "https://www.koreabaseball.com/ws"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
REGULAR = 0   # SR_ID 0 = 정규시즌 (1 시범, 3~5·7 포스트시즌, 9 올스타)
FIELDS = ["date", "season", "gid", "stadium", "home", "away",
          "home_sp", "away_sp", "home_sp_id", "away_sp_id",
          "home_5", "away_5", "home_final", "away_final", "innings",
          "home_innings", "away_innings", "home_hr", "away_hr"]


def post(path, data):
    r = requests.post(f"{BASE}/{path}", data=data, headers=HEADERS, timeout=15)
    r.raise_for_status()
    if not r.text.lstrip("﻿").startswith("{"):
        raise RuntimeError(f"{path}: JSON이 아닌 응답 (사이트 구조가 바뀌었을 수 있어요)")
    return r.json()


def games_on(day):
    """그날 정규시즌 경기 중 정상 종료된 것만."""
    d = post("Main.asmx/GetKboGameList", {"leId": 1, "srId": "0,1,3,4,5,7,9", "date": day.strftime("%Y%m%d")})
    return [g for g in d.get("game", [])
            if g["SR_ID"] == REGULAR and g["GAME_STATE_SC"] == "3" and str(g["CANCEL_SC_ID"]) == "0"]


def innings(g):
    """이닝별 득점. 반환: (원정 리스트, 홈 리스트). '-'(안 한 이닝)·'X'(말 공격 생략)는 빼요."""
    d = post("Schedule.asmx/GetScoreBoardScroll",
             {"leId": 1, "srId": g["SR_ID"], "seasonId": g["SEASON_ID"], "gameId": g["G_ID"]})
    rows = json.loads(d["table2"])["rows"]

    def runs(row):
        out = []
        for c in row["row"]:
            t = c["Text"].strip()
            if t.isdigit():
                out.append(int(t))
            elif t.upper() == "X":
                out.append(None)  # 홈팀이 이겨서 9회말을 안 한 경우
        return out

    return runs(rows[0]), runs(rows[1])


def homeruns(sr_id, season, gid):
    """팀 홈런 수 (홈, 원정). 박스스코어 투수 기록의 피홈런을 더해요.
    투수 표는 [원정 투수들, 홈 투수들] 순서라 원정 투수 피홈런 합 = 홈팀 홈런."""
    d = post("Schedule.asmx/GetBoxScoreScroll", {"leId": 1, "srId": sr_id, "seasonId": season, "gameId": gid})
    sums = []
    for t in d["arrPitcher"]:
        tab = json.loads(t["table"])
        col = [c["Text"] for c in tab["headers"][0]["row"]].index("홈런")
        sums.append(sum(int(r["row"][col]["Text"]) for r in tab["rows"]))
    away_pitch, home_pitch = sums
    return away_pitch, home_pitch


def to_row(g, inn):
    row = {
        "date": datetime.strptime(g["G_DT"], "%Y%m%d").date().isoformat(),
        "season": g["SEASON_ID"], "gid": g["G_ID"], "stadium": g["S_NM"],
        "home": g["HOME_NM"], "away": g["AWAY_NM"],
        # T = 초(원정), B = 말(홈)
        "home_sp": (g["B_PIT_P_NM"] or "").strip(), "away_sp": (g["T_PIT_P_NM"] or "").strip(),
        "home_sp_id": g["B_PIT_P_ID"] or "", "away_sp_id": g["T_PIT_P_ID"] or "",
        "home_final": int(g["B_SCORE_CN"]), "away_final": int(g["T_SCORE_CN"]),
        "innings": g["GAME_INN_NO"],
        "home_5": "", "away_5": "", "home_innings": "", "away_innings": "",
    }
    if inn:
        a, h = inn
        row["away_5"] = sum(a[:5]) if len(a) >= 5 else ""
        row["home_5"] = sum(x or 0 for x in h[:5]) if len(h) >= 5 else ""
        row["away_innings"] = " ".join(str(x) for x in a)
        row["home_innings"] = " ".join("X" if x is None else str(x) for x in h)
    return row


def load_existing(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", help="시작일 YYYYMMDD")
    ap.add_argument("--to", dest="end", help="종료일 YYYYMMDD (기본: 어제)")
    ap.add_argument("--season", type=int, help="시즌 전체 (3/20 ~ 10/31)")
    ap.add_argument("--out", default="kbo_games.csv")
    ap.add_argument("--no-innings", action="store_true", help="이닝별 점수 생략 (요청 수 1/6)")
    ap.add_argument("--delay", type=float, default=0.7)
    ap.add_argument("--fill-hr", action="store_true", help="이미 모은 경기 중 홈런 칸이 빈 경기만 채우기")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    if args.fill_hr:
        fill_hr(out, args.delay)
        return

    if args.season:
        start, end = date(args.season, 3, 20), date(args.season, 10, 31)
    elif args.start:
        start = datetime.strptime(args.start, "%Y%m%d").date()
        end = datetime.strptime(args.end, "%Y%m%d").date() if args.end else date.today() - timedelta(days=1)
    else:
        ap.error("--from 또는 --season 을 지정하세요")
    end = min(end, date.today())

    rows = load_existing(out)
    seen = {r["gid"] for r in rows}
    added = 0

    day = start
    while day <= end:
        try:
            gs = games_on(day)
        except Exception as e:
            print(f"{day} 실패: {e}", file=sys.stderr)
            gs = []
        time.sleep(args.delay)
        for g in gs:
            if g["G_ID"] in seen:
                continue
            inn = None
            if not args.no_innings:
                try:
                    inn = innings(g)
                except Exception as e:
                    print(f"  {g['G_ID']} 이닝 점수 실패: {e}", file=sys.stderr)
                time.sleep(args.delay)
            row = to_row(g, inn)
            if not args.no_innings:
                try:
                    row["home_hr"], row["away_hr"] = homeruns(g["SR_ID"], g["SEASON_ID"], g["G_ID"])
                except Exception as e:
                    print(f"  {g['G_ID']} 홈런 실패: {e}", file=sys.stderr)
                time.sleep(args.delay)
            rows.append(row)
            seen.add(g["G_ID"])
            added += 1
        if gs:
            print(f"{day}: {len(gs)}경기", flush=True)
        day += timedelta(days=1)

    save(out, rows)
    print(f"저장: {out}  (새 경기 {added}개, 전체 {len(rows)}개)")


def save(out, rows):
    rows.sort(key=lambda r: (r["date"], r["gid"]))
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def fill_hr(out, delay):
    """홈런 칸이 빈 경기만 박스스코어를 받아 채워요. 100경기마다 중간 저장해서 끊겨도 이어서 돼요."""
    rows = load_existing(out)
    todo = [r for r in rows if r.get("home_hr", "") in ("", None)]
    print(f"홈런 채울 경기 {len(todo)}개 (약 {len(todo) * (delay + 0.3) / 60:.0f}분)", flush=True)
    for i, r in enumerate(todo, 1):
        try:
            r["home_hr"], r["away_hr"] = homeruns(REGULAR, r["season"], r["gid"])
        except Exception as e:
            print(f"  {r['gid']} 실패: {e}", file=sys.stderr)
        time.sleep(delay)
        if i % 100 == 0:
            save(out, rows)
            print(f"  {i}/{len(todo)}", flush=True)
    save(out, rows)
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
