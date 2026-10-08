"""
KBL 기록 API에서 JSON을 받아 파일로 저장하는 도구 (당신 PC에서 실행하세요)

사용법:
    python fetch_kbl.py "https://kbl-api.sports2i.com/api/v1/season-leaders/teams?seasonCode=47&gameCode=01"

결과: data/ 폴더에 JSON 파일이 저장돼요. 구조를 확인한 뒤 games.csv / last_season.csv로 바꾸는 코드를 만들면 돼요.

알아둔 값:
    seasonCode  49 = 2026-27, 47 = 2025-26, 45 = 2024-25 (시즌마다 2씩 차이)
    gameCode    01 = 정규리그로 추정

예의: 요청 사이에 1초 이상 쉬고, 개인 학습 용도로만 쓰세요.
"""

import json
import pathlib
import re
import sys
import time

import requests

HEADERS = {
    # 브라우저에서 보낸 것과 비슷하게 맞춰야 403이 안 나요.
    # 그래도 막히면 DevTools에서 요청을 우클릭 → Copy as cURL 해서 헤더를 비교하세요.
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.kbl.or.kr/",
    "Origin": "https://www.kbl.or.kr",
    "Accept": "application/json",
}


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


def save(url, data):
    out = pathlib.Path("data")
    out.mkdir(exist_ok=True)
    name = re.sub(r"[^0-9A-Za-z]+", "_", url.split("/api/")[-1]).strip("_")
    path = out / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    for url in sys.argv[1:]:
        data = fetch(url)
        path = save(url, data)
        print(f"저장: {path}")
        # 구조 미리보기
        if isinstance(data, dict):
            print("  최상위 키:", list(data.keys())[:15])
        elif isinstance(data, list):
            print(f"  리스트 {len(data)}개, 첫 항목:", json.dumps(data[0], ensure_ascii=False)[:300] if data else "없음")
        time.sleep(1)
