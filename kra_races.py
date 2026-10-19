"""
한국마사회(KRA) 경주 성적 수집기 (경마 1착 확률 분석용)

사용법
  python kra_races.py --probe --month 202609                 # 응답 필드 이름 확인 (처음 한 번)
  python kra_races.py --from 20250101 --to 20261012          # 기간 수집 → kra_races.csv
  python kra_races.py                                        # 마지막 수집일 이후 ~ 어제 (매일 돌리면 새 경주만 붙어요)
  python kra_races.py --meet 1                               # 서울만 (기본: 1,3 = 서울·부경)

인증키 (공공데이터포털 data.go.kr 에서 무료 발급)
  1. data.go.kr 회원가입 → '한국마사회_경주성적정보' 검색 → 활용신청 (자동 승인, 반영까지 1시간쯤 걸려요)
  2. 마이페이지 → 일반 인증키(Decoding) 복사
  3. 아래 중 하나로 넣기
       - 환경변수 KRA_KEY  (PowerShell: $env:KRA_KEY = "키")
       - 이 폴더에 kra_key.txt 파일로 저장 (.gitignore 에 들어 있어 커밋 안 돼요)
       - --key "키"

데이터: 공공데이터포털 한국마사회_경주성적정보 (B551015/API214_1/RaceDetailResult_1)
  경마장 코드: 1 서울, 2 제주, 3 부산경남, 4 영천
경주마다 말 한 줄씩: 날짜·경마장·경주번호·거리·등급·주로·말·출전번호·순위·부담중량·마체중·기수·조교사·단승/연승 배당.
이미 kra_races.csv 에 있는 줄은 건너뛰어요. 취소·제외된 말도 순위 0 으로 저장해요 (예측기가 빼고 써요).

필요 패키지: pip install requests truststore
"""
import argparse
import csv
import json
import os
import pathlib
import re
import sys
import time
from datetime import date, datetime, timedelta
from urllib.parse import unquote

import requests

try:
    # data.go.kr 도 중간 인증서를 안 보내서, 윈도우 인증서 저장소를 쓰게 해요 (kbo_scores.py와 같은 이유)
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

URL = "https://apis.data.go.kr/B551015/API214_1/RaceDetailResult_1"
MEET_NAMES = {"1": "서울", "2": "제주", "3": "부경", "4": "영천"}
MEET_CODES = {"서울": "1", "제주": "2", "부경": "3", "부산경남": "3", "부산": "3", "영천": "4"}

FIELDS = ["date", "meet", "rc_no", "dist", "grade", "track", "weather",
          "horse_no", "horse", "gate", "finish", "finish_note", "age", "sex", "rating",
          "burden", "horse_wt", "wt_change", "jockey", "jockey_no", "trainer", "trainer_no",
          "time", "win_odds", "plc_odds"]

# 응답 필드 이름 후보. 공식 문서(docx)를 직접 못 봐서 흔히 쓰는 이름을 모아뒀어요.
# --probe 로 실제 이름을 보고 다르면 여기 맨 앞에 추가하세요.
CANDIDATES = {
    "date": ["rcDate", "rc_date"],
    "meet": ["meet"],
    "rc_no": ["rcNo", "rc_no"],
    "dist": ["rcDist", "rc_dist"],
    "grade": ["rank", "rcRank", "grade"],
    "track": ["track", "trackCondition"],
    "weather": ["weather"],
    "horse_no": ["hrNo", "hr_no"],
    "horse": ["hrName", "hr_name", "hrNm"],
    "gate": ["chulNo", "chul_no", "chulNum"],
    "finish": ["ord", "rcOrd", "rank_ord"],
    "finish_note": ["ordBigo", "ord_bigo"],
    "age": ["age"],
    "sex": ["sex"],
    "rating": ["rating"],
    "burden": ["wgBudam", "budam", "wg_budam"],
    "horse_wt": ["wgHr", "wg_hr", "hrWeight"],
    "jockey": ["jkName", "jk_name"],
    "jockey_no": ["jkNo", "jk_no"],
    "trainer": ["trName", "tr_name"],
    "trainer_no": ["trNo", "tr_no"],
    "time": ["rcTime", "rc_time"],
    "win_odds": ["winOdds", "win_odds", "dansung"],
    "plc_odds": ["plcOdds", "plc_odds", "yunsung"],
}


def load_key(arg):
    key = arg or os.environ.get("KRA_KEY")
    p = pathlib.Path("kra_key.txt")
    if not key and p.exists():
        key = p.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit("인증키가 없어요. 파일 맨 위 설명대로 KRA_KEY 환경변수나 kra_key.txt 를 만들어 주세요.")
    # 'Encoding' 키(%2B 같은 게 들어간 것)를 넣어도 되게 풀어줘요. requests 가 다시 인코딩해요.
    return unquote(key) if "%" in key else key


def fetch_page(key, meet, month, page, rows=1000):
    params = {"serviceKey": key, "pageNo": page, "numOfRows": rows,
              "meet": meet, "rc_month": month, "_type": "json"}
    r = requests.get(URL, params=params, timeout=30)
    r.raise_for_status()
    text = r.text.lstrip("﻿")
    if not text.startswith("{"):
        # 키 오류 등은 JSON 이 아니라 XML 로 와요
        msg = re.search(r"<returnAuthMsg>(.*?)</returnAuthMsg>|<resultMsg>(.*?)</resultMsg>", text)
        raise RuntimeError(f"JSON이 아닌 응답: {(msg.group(1) or msg.group(2)) if msg else text[:200]}"
                           "\n  (SERVICE_KEY_IS_NOT_REGISTERED_ERROR 면 활용신청 후 1시간쯤 기다리거나 Decoding 키를 쓰세요)")
    body = r.json().get("response", {})
    head = body.get("header", {})
    if str(head.get("resultCode", "00")) not in ("00", "0"):
        raise RuntimeError(f"API 오류 {head.get('resultCode')}: {head.get('resultMsg')}")
    b = body.get("body", {}) or {}
    items = (b.get("items") or {})
    items = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(items, dict):  # 한 건이면 리스트가 아니라 dict 로 와요
        items = [items]
    return items, int(b.get("totalCount") or 0)


def fetch_month(key, meet, month, delay):
    out, page = [], 1
    while True:
        items, total = fetch_page(key, meet, month, page)
        out += items
        time.sleep(delay)
        if not items or len(out) >= total:
            return out
        page += 1


def pick(item, name):
    low = {k.lower(): v for k, v in item.items()}
    for c in CANDIDATES[name]:
        if c in item:
            return item[c]
        if c.lower() in low:
            return low[c.lower()]
    return ""


def num(v):
    m = re.search(r"-?\d+(\.\d+)?", str(v))
    return m.group(0) if m else ""


def to_row(item):
    r = {f: pick(item, f) for f in CANDIDATES}
    d = re.sub(r"\D", "", str(r["date"]))[:8]
    r["date"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else r["date"]
    m = str(r["meet"]).strip()
    r["meet"] = MEET_CODES.get(m, m)
    for f in ("rc_no", "dist", "gate", "finish", "age", "rating", "burden", "win_odds", "plc_odds"):
        r[f] = num(r[f])
    # 마체중은 보통 "498(-2)" 처럼 와요 → 체중 498, 증감 -2
    wt = str(r["horse_wt"])
    m = re.match(r"\s*(\d+)\s*\(\s*([+-]?\d+)\s*\)", wt)
    r["horse_wt"], r["wt_change"] = (m.group(1), str(int(m.group(2)))) if m else (num(wt), "")
    if r["finish"] == "":
        r["finish"] = "0"
    return {f: r.get(f, "") for f in FIELDS}


def load_existing(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def save(path, rows):
    rows.sort(key=lambda r: (r["date"], r["meet"], int(r["rc_no"] or 0), int(r["finish"] or 0) or 99))
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def months(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y}{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", help="시작일 YYYYMMDD (기본: 파일의 마지막 날짜)")
    ap.add_argument("--to", dest="end", help="종료일 YYYYMMDD (기본: 어제)")
    ap.add_argument("--meet", default="1,3", help="경마장 코드 (1 서울, 2 제주, 3 부경, 4 영천)")
    ap.add_argument("--out", default="kra_races.csv")
    ap.add_argument("--key", help="공공데이터포털 인증키 (기본: KRA_KEY 환경변수 또는 kra_key.txt)")
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--probe", action="store_true", help="응답 첫 항목의 원래 필드 이름을 보여주기")
    ap.add_argument("--month", help="--probe 할 달 YYYYMM")
    args = ap.parse_args()

    key = load_key(args.key)
    meets = [m.strip() for m in args.meet.split(",") if m.strip()]

    if args.probe:
        month = args.month or (date.today().replace(day=1) - timedelta(days=1)).strftime("%Y%m")
        items, total = fetch_page(key, meets[0], month, 1, rows=3)
        print(f"{MEET_NAMES.get(meets[0], meets[0])} {month}: 전체 {total}줄")
        if items:
            print(json.dumps(items[0], ensure_ascii=False, indent=2))
            missing = [f for f in CANDIDATES if pick(items[0], f) == ""]
            print("\n못 찾은 칸:", ", ".join(missing) or "없음")
            print("→ 못 찾은 칸이 있으면 위 원래 이름을 CANDIDATES 에 추가하세요.")
        return

    out = pathlib.Path(args.out)
    rows = load_existing(out)
    seen = {(r["date"], r["meet"], r["rc_no"], r["horse_no"] or r["horse"]) for r in rows}

    if args.start:
        start = datetime.strptime(args.start, "%Y%m%d").date()
    elif rows:
        start = max(datetime.strptime(r["date"], "%Y-%m-%d").date() for r in rows)
    else:
        ap.error("처음에는 --from 을 지정하세요 (예: --from 20240101)")
    end = datetime.strptime(args.end, "%Y%m%d").date() if args.end else date.today() - timedelta(days=1)

    added = 0
    for month in months(start, end):
        for meet in meets:
            try:
                items = fetch_month(key, meet, month, args.delay)
            except Exception as e:
                print(f"{month} {MEET_NAMES.get(meet, meet)} 실패: {e}", file=sys.stderr)
                continue
            new = 0
            for it in items:
                r = to_row(it)
                if not (start.isoformat() <= r["date"] <= end.isoformat()):
                    continue
                k = (r["date"], r["meet"], r["rc_no"], r["horse_no"] or r["horse"])
                if k in seen:
                    continue
                seen.add(k)
                rows.append(r)
                new += 1
            added += new
            print(f"{month} {MEET_NAMES.get(meet, meet)}: {len(items)}줄 받음, 새로 {new}줄", flush=True)

    if rows:
        save(out, rows)
    races = len({(r["date"], r["meet"], r["rc_no"]) for r in rows})
    print(f"저장: {out}  (새 줄 {added}개, 전체 {len(rows)}줄 / 경주 {races}개)")


if __name__ == "__main__":
    main()
