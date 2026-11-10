"""
V리그 정규리그 경기 결과(세트별 점수) 수집기 → vb_games.csv

사용법
  python vb_fetch.py 023                 # 2026-27 시즌 받아서 vb_games.csv 갱신 (kovo_023.json도 저장)
  python vb_fetch.py 022 023             # 여러 시즌
  python vb_fetch.py --from-json kovo_021.json kovo_022.json   # 받아 둔 JSON만 변환

시즌 코드: 001 = 2005, 시즌마다 +1 → 020 = 2023-24, 021 = 2024-25, 022 = 2025-26, 023 = 2026-27
정규리그만 씀 (leagueCode 201). 같은 경기는 덮어써서, 몇 번을 돌려도 중복되지 않아요.

예의: 요청 사이 1초 이상 쉬고, 개인 학습 용도로만 쓰세요.
필요 패키지: pip install requests truststore
"""
import argparse
import csv
import json
import pathlib
import sys
import time

URL = "https://user-api.kovo.co.kr/stat/game-schedule?seasonCode={code}&leagueCode=201&size=1000&page=0"
REGULAR = "201"

TEAM_NAMES = {
    "1001": "대한항공", "1002": "삼성화재", "1004": "KB손해보험", "1005": "현대캐피탈",
    "1006": "한국전력", "1008": "OK저축은행", "1009": "우리카드",
    "2001": "현대건설", "2002": "한국도로공사", "2003": "정관장", "2004": "흥국생명",
    "2005": "GS칼텍스", "2006": "IBK기업은행", "2007": "페퍼저축은행", "2008": "SOOP",
}

COLUMNS = ["date", "season", "gender", "gnum", "home", "away", "home_sets", "away_sets",
           "h1", "h2", "h3", "h4", "h5", "a1", "a2", "a3", "a4", "a5", "played"]


def season_name(code):
    """'023' → '2026-27'"""
    start = int(code) + 2003
    return f"{start}-{(start + 1) % 100:02d}"


def rows_from_json(data):
    rows = []
    for x in data["payload"]["content"]:
        if x.get("leagueCode") != REGULAR:
            continue
        played = 1 if x.get("score") else 0
        row = {
            "date": x["gdate"], "season": season_name(x["seasonCode"]), "gender": str(x["gender"]),
            "gnum": int(x["gnum"]),
            "home": TEAM_NAMES.get(x["hcode"], x["hname"]), "away": TEAM_NAMES.get(x["acode"], x["aname"]),
            "home_sets": int(x["hspoint"] or 0), "away_sets": int(x["aspoint"] or 0),
            "played": played,
        }
        for i in range(1, 6):
            row[f"h{i}"] = int(x.get(f"hs{i}point") or 0)
            row[f"a{i}"] = int(x.get(f"as{i}point") or 0)
        rows.append(row)
    return rows


def _key(r):
    return (r["season"], str(r["gender"]), int(r["gnum"]))


def merge_rows(existing, new):
    merged = {_key(r): r for r in existing}
    merged.update({_key(r): r for r in new})
    return sorted(merged.values(), key=lambda r: (r["date"], str(r["gender"]), int(r["gnum"])))


def read_csv(path):
    p = pathlib.Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r[c] for c in COLUMNS})


def download(code):
    try:
        import truststore  # 윈도우 인증서 저장소 사용 (kbl_scores.py와 같은 이유)
        truststore.inject_into_ssl()
    except ImportError:
        pass
    import requests
    r = requests.get(URL.format(code=code), headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    r.raise_for_status()
    data = r.json()
    pathlib.Path(f"kovo_{code}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="V리그 정규리그 결과 → vb_games.csv")
    ap.add_argument("seasons", nargs="*", help="시즌 코드 (예: 023)")
    ap.add_argument("--from-json", nargs="+", metavar="FILE", help="받아 둔 KOVO JSON 파일만 변환")
    ap.add_argument("--out", default="vb_games.csv")
    args = ap.parse_args()
    if not args.seasons and not args.from_json:
        ap.error("시즌 코드나 --from-json 중 하나는 있어야 해요")

    new = []
    for path in args.from_json or []:
        new += rows_from_json(json.loads(pathlib.Path(path).read_text(encoding="utf-8")))
    for i, code in enumerate(args.seasons):
        if i:
            time.sleep(1)
        try:
            new += rows_from_json(download(code))
        except Exception as e:  # 네트워크·차단·형식 오류 모두 같은 안내
            print(f"{code} 시즌을 받지 못했어요: {e}")
            print("브라우저에서 kovo.co.kr 일정/결과 페이지 → F12 → Network → 'game-schedule' 응답을 "
                  f"kovo_{code}.json으로 저장한 뒤 python vb_fetch.py --from-json kovo_{code}.json 으로 넣어 주세요.")
            sys.exit(1)

    rows = merge_rows(read_csv(args.out), new)
    write_csv(args.out, rows)
    done = sum(1 for r in rows if int(r["played"]))
    print(f"{args.out} 저장: {len(rows)}경기 (끝난 경기 {done}, 예정 {len(rows) - done})")


if __name__ == "__main__":
    main()
