"""
KBL 팀기록 화면(1차 스탯, 누적)의 HTML을 팀 평균표 CSV로 바꾸기

사용법:
    1. KBL 기록 → 팀기록 → 시즌 선택, '정규시즌', '1차 스탯', '누적'
    2. F12 → Elements에서 표가 있는 <div class="contents"> 를 우클릭 → Copy outerHTML
    3. 메모장에 붙여넣어 team_table.html 로 저장
    4. python parse_team_table.py team_table.html                       → last_season.csv
       python parse_team_table.py t2024.html --out season_2024-25.csv  → 다른 이름으로 저장
       python parse_team_table.py r1.html r2.html r3.html --out prior_r1-3.csv  → 여러 표(라운드별) 합치기

실점 계산: 표의 +/- 는 코트 위 5명의 득실마진 합이라 5로 나눠요.
    경기당 실점 = (총득점 - (+/-) / 5) / 경기수
"""

import csv
import re
import sys


def parse(html):
    """팀별 누적 합계(경기 수, 총득점, 총마진)를 돌려줘요."""
    head = html.split("<thead>")[1].split("</thead>")[0]
    keys = re.findall(r'data-key="([^"]+)"', head)
    body = html.split("<tbody>")[1].split("</tbody>")[0]

    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        if "합계" in tr:
            continue
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        row = dict(zip(keys, cells))
        rows.append({
            "team": row["팀"].replace(" ", ""),
            "games": int(row["G"]),
            "pts_total": int(row["PTS"]),
            "margin_total": int(row["+/-"]) / 5,
        })
    return rows


if __name__ == "__main__":
    args = sys.argv[1:]
    out = "last_season.csv"
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        args = args[:i] + args[i + 2:]
    srcs = args or ["team_table.html"]

    # 여러 표(라운드별 등)는 팀별로 누적 합계를 더한 뒤 평균을 내요
    total = {}
    for src in srcs:
        for r in parse(open(src, encoding="utf-8").read()):
            t = total.setdefault(r["team"], {"games": 0, "pts_total": 0, "margin_total": 0.0})
            for k in ("games", "pts_total", "margin_total"):
                t[k] += r[k]
    rows = [{"team": team, "games": t["games"],
             "pts": round(t["pts_total"] / t["games"], 1),
             "opp_pts": round((t["pts_total"] - t["margin_total"]) / t["games"], 1)}
            for team, t in total.items()]

    total_margin = sum((r["pts"] - r["opp_pts"]) * r["games"] for r in rows)
    print(f"{'팀':12}{'경기':>4}{'득점':>7}{'실점':>7}{'마진':>7}")
    for r in sorted(rows, key=lambda r: r["opp_pts"]):
        print(f"{r['team']:12}{r['games']:>4}{r['pts']:>7}{r['opp_pts']:>7}"
              f"{r['pts'] - r['opp_pts']:>+7.1f}")
    print(f"\n검증: 리그 전체 마진 합 = {total_margin:.0f} (0에 가까우면 정상)")

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team", "pts", "opp_pts", "memo"])
        for r in rows:
            w.writerow([r["team"], r["pts"], r["opp_pts"],
                        f"KBL 팀기록 정규시즌 {r['games']}경기 ({', '.join(srcs)})"])
    print(f"{out} 저장 완료")
