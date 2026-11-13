"""
WKBL(여자농구) 정규리그 경기 결과(전반/최종 점수) 수집기

사용법
    python wkbl_scores.py                    # 이번 시즌(2026-27) → wkbl_games.csv
    python wkbl_scores.py --season 2025-26   # 지난 시즌 → wkbl_games_2025-26.csv + wkbl_season_2025-26.csv

이미 저장된 경기는 다시 받지 않아요. 매일 돌리면 새로 끝난 경기만 추가돼요.

자료: wkbl.or.kr 경기 결과 페이지 (game/result.asp). 페이지 위쪽 팀 칸의 class 이름이
home/away로 붙어 있지만 실제로는 반대예요. 경기장으로 확인해 보면 먼저 나오는 팀(class="away")이 홈팀이에요.
(예: 2026-27 1번 경기 청주체육관 → KB스타즈가 먼저 나옴)

예의: 요청 사이에 1초씩 쉬어요. 개인 학습 용도로만 쓰세요.
"""
import argparse
import csv
import pathlib
import re
import sys
import time

import requests

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

URL = ("https://www.wkbl.or.kr/game/result.asp?season_gu={code}&gun=1&game_type=01"
       "&game_no={no}&viewType=2")
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.wkbl.or.kr/"}
FIELDS = ["date", "season", "gmkey", "home", "away", "home_half", "away_half", "home_final", "away_final"]
MAX_GAMES = 90        # 정규리그: 6팀 × 30경기 / 2
STOP_AFTER_EMPTY = 4  # 아직 안 한 경기가 이만큼 연달아 나오면 그만 받기


def season_code(season):
    """'2026-27' → '047'. 2025-26 = 046 (WKBL 사이트 season_gu, 1년에 1씩 증가)."""
    return f"{int(season[:4]) - 1979:03d}"


def team_name(s):
    return s.replace(" ", "")  # 'BNK 썸' → 'BNK썸'


def fetch_game(code, no):
    """경기 1개: dict 또는 None(아직 안 했거나 없는 경기)."""
    r = requests.get(URL.format(code=code, no=no), headers=HEADERS, timeout=15)
    if r.status_code == 500:
        return None  # 아직 안 한 경기는 사이트가 500 에러를 돌려줘요
    r.raise_for_status()
    s = r.content.decode("utf-8", "replace")
    info = re.search(r'class="info_game">(.*?)</p>', s, re.S)
    tbody = re.search(r"<tbody>(.*?)</tbody>", s, re.S)
    if not info or not tbody:
        return None
    d = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", info.group(1))
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", tbody.group(1), re.S):
        name = re.search(r'data-kr="([^"]*)"', tr)
        nums = [int(x) for x in re.findall(r"<td>\s*(\d+)\s*</td>", tr)]
        if name and len(nums) >= 6:
            rows.append((team_name(name.group(1)), nums))
    if not d or len(rows) != 2:
        return None
    (home, hq), (away, aq) = rows  # 먼저 나오는 팀이 홈팀
    if hq[-1] == 0 and aq[-1] == 0:
        return None  # 아직 안 한 경기
    return {
        "date": f"{d.group(1)}-{int(d.group(2)):02d}-{int(d.group(3)):02d}",
        "gmkey": f"W{code}G{no:03d}",
        "home": home, "away": away,
        "home_half": hq[0] + hq[1], "away_half": aq[0] + aq[1],
        "home_final": hq[-1], "away_final": aq[-1],
    }


def collect(season, out_path):
    code = season_code(season)
    path = pathlib.Path(out_path)
    have = {}
    if path.exists():
        with path.open(encoding="utf-8-sig") as f:
            have = {r["gmkey"]: r for r in csv.DictReader(f)}
    empty = 0
    added = 0
    for no in range(1, MAX_GAMES + 1):
        key = f"W{code}G{no:03d}"
        if key in have:
            empty = 0
            continue
        g = fetch_game(code, no)
        time.sleep(1)
        if g is None:
            empty += 1
            if empty >= STOP_AFTER_EMPTY:
                break
            continue
        empty = 0
        g["season"] = season
        have[key] = g
        added += 1
        print(f"  {g['date']} {g['home']} {g['home_final']} - {g['away_final']} {g['away']}")
    games = sorted(have.values(), key=lambda r: (r["date"], r["gmkey"]))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for g in games:
            w.writerow({k: g[k] for k in FIELDS})
    print(f"{path}: 새로 {added}경기, 전체 {len(games)}경기")
    return games


def write_team_table(games, season, out_path):
    """시즌 팀별 평균 득점·실점표 (predict.py --prior 용)."""
    tot = {}
    for g in games:
        for t, p, o in ((g["home"], g["home_final"], g["away_final"]),
                        (g["away"], g["away_final"], g["home_final"])):
            s = tot.setdefault(t, [0, 0, 0])
            s[0] += int(p)
            s[1] += int(o)
            s[2] += 1
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["team", "pts", "opp_pts", "memo"])
        for t, (p, o, n) in sorted(tot.items(), key=lambda kv: -(kv[1][0] - kv[1][1]) / kv[1][2]):
            w.writerow([t, round(p / n, 1), round(o / n, 1), f"WKBL {season} 정규리그 {n}경기 (wkbl_scores.py)"])
    print(f"{out_path}: {len(tot)}팀")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026-27")
    ap.add_argument("--out", help="기본: 이번 시즌 wkbl_games.csv, 지난 시즌 wkbl_games_<시즌>.csv")
    a = ap.parse_args()
    current = a.season == "2026-27"
    out = a.out or ("wkbl_games.csv" if current else f"wkbl_games_{a.season}.csv")
    games = collect(a.season, out)
    if not current:
        write_team_table(games, a.season, f"wkbl_season_{a.season}.csv")
