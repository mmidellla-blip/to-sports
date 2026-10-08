"""
KBL 팀기록 화면(1차 스탯, 누적)의 HTML을 last_season.csv로 바꾸기

사용법:
    1. KBL 기록 → 팀기록 → 시즌 선택, '정규시즌', '1차 스탯', '누적'
    2. F12 → Elements에서 표가 있는 <div class="contents"> 를 우클릭 → Copy outerHTML
    3. 메모장에 붙여넣어 team_table.html 로 저장
    4. python parse_team_table.py team_table.html

실점 계산: 표의 +/- 는 코트 위 5명의 득실마진 합이라 5로 나눠요.
    경기당 실점 = (총득점 - (+/-) / 5) / 경기수
"""

import csv
import re
import sys


def parse(html):
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
        g = int(row["G"])
        pts = int(row["PTS"])
        margin = int(row["+/-"]) / 5
        rows.append({
            "team": row["팀"].replace(" ", ""),
            "games": g,
            "pts": round(pts / g, 1),
            "opp_pts": round((pts - margin) / g, 1),
        })
    return rows


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "team_table.html"
    rows = parse(open(src, encoding="utf-8").read())

    total_margin = sum((r["pts"] - r["opp_pts"]) * r["games"] for r in rows)
    print(f"{'팀':12}{'경기':>4}{'득점':>7}{'실점':>7}{'마진':>7}")
    for r in sorted(rows, key=lambda r: r["opp_pts"]):
        print(f"{r['team']:12}{r['games']:>4}{r['pts']:>7}{r['opp_pts']:>7}"
              f"{r['pts'] - r['opp_pts']:>+7.1f}")
    print(f"\n검증: 리그 전체 마진 합 = {total_margin:.0f} (0에 가까우면 정상)")

    with open("last_season.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["team", "pts", "opp_pts", "memo"])
        for r in rows:
            w.writerow([r["team"], r["pts"], r["opp_pts"],
                        f"KBL 팀기록 정규시즌 {r['games']}경기"])
    print("last_season.csv 저장 완료")
