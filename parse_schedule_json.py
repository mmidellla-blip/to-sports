"""
KBL 경기 → 일정/결과 화면의 Network 응답(JSON)을 games CSV로 바꾸기
월별로 저장한 여러 파일을 한 번에 넣으면 합쳐줘요. 같은 경기는 한 번만 들어가요.

사용법:
    python parse_schedule_json.py schedule_2025-10.json schedule_2025-11.json ... --out games_2025-26.csv

- 정규시즌(gameCode 01), 끝난 경기(isEnded 1)만 넣어요
- 이 응답에는 쿼터 점수가 없어서 전반 칸은 비워둬요
"""
import csv
import json
import sys

args = sys.argv[1:]
out = "games_season.csv"
if "--out" in args:
    i = args.index("--out"); out = args[i + 1]; args = args[:i] + args[i + 2:]

games = {}
for path in args:
    data = json.load(open(path, encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("data", [])
    for g in data:
        if g.get("gameCode") != "01" or not g.get("isEnded"):
            continue
        d = g["gameDate"]
        y, m = int(d[:4]), int(d[4:6])
        start = y if m >= 7 else y - 1
        games[g["gmkey"]] = {
            "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
            "season": f"{start}-{str(start + 1)[2:]}",
            "home": g["tnameH"].replace(" ", ""),
            "away": g["tnameA"].replace(" ", ""),
            "home_half": "", "away_half": "",
            "home_final": g["scoreH"], "away_final": g["scoreA"],
        }

rows = sorted(games.values(), key=lambda r: r["date"])
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["date", "season", "home", "away", "home_half", "away_half", "home_final", "away_final"])
    w.writeheader(); w.writerows(rows)

months = sorted({r["date"][:7] for r in rows})
print(f"{out} 저장: {len(rows)}경기 ({months[0]} ~ {months[-1]})" if rows else "경기가 없어요")
teams = {}
for r in rows:
    for t in (r["home"], r["away"]):
        teams[t] = teams.get(t, 0) + 1
print("팀별 경기 수:", ", ".join(f"{t} {n}" for t, n in sorted(teams.items())))
if rows:
    tot = sum(r["home_final"] + r["away_final"] for r in rows) / len(rows)
    home_w = sum(r["home_final"] > r["away_final"] for r in rows) / len(rows)
    print(f"평균 합계 {tot:.1f}점, 홈팀 승률 {home_w:.0%}")
