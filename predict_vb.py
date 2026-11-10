"""
V리그 승패·세트스코어 예측기

사용법
  python predict_vb.py --date 20261110                      # 그날 경기 전부
  python predict_vb.py --home 현대캐피탈 --away 대한항공     # 두 팀 지정 (남/여 자동)
  python predict_vb.py --backtest --season 2025-26          # 시즌 백테스트 (경기 전날까지 데이터만 사용)
  python predict_vb.py --tune --season 2024-25              # 설정값 격자 탐색

데이터: vb_games.csv (python vb_fetch.py 로 수집)

계산 방식 (경기마다)
  1. 득점률 레이팅 = 시즌 랠리 득점률의 로짓, 상대 강도 보정 후 리그 평균 0
  2. 이번 시즌 n경기를 n/(n+K)만큼 믿고, 나머지는 지난 시즌 레이팅 × REGRESS
  3. 홈 랠리 승률 p = sigmoid(SCALE × (홈 레이팅 − 원정 레이팅) + HOME)
  4. 세트 승률 = 랠리 독립 가정의 정확식 (25점 / 5세트 15점, 듀스 2점차)
  5. 세트스코어 = 세트 승률로 3:0 ~ 0:3 확률. 경기 컨디션 흔들림 SIGMA를 로짓에 더해 평균
     (세트를 독립으로 보면 접전을 너무 많이, 일방적인 경기를 너무 적게 봐서 그걸 고침)
"""
import argparse
import csv
import math
import sys
from collections import Counter, defaultdict
from math import comb

import numpy as np

# ── 설정값 ──
K = 8            # 이번 시즌 반영 속도 (경기 수)
REGRESS = 0.4    # 지난 시즌 레이팅을 얼마나 남길지
SCALE = 1.2      # 레이팅 차이 배율
SIGMA = 0.2      # 경기 컨디션 흔들림 (로짓 단위 표준편차)

SCORES = [(3, 0), (3, 1), (3, 2), (2, 3), (1, 3), (0, 3)]
GENDER_NAME = {"1": "남자부", "2": "여자부"}
_INT_COLS = ["gnum", "home_sets", "away_sets", "h1", "h2", "h3", "h4", "h5",
             "a1", "a2", "a3", "a4", "a5", "played"]
_GH_X, _GH_W = np.polynomial.hermite_e.hermegauss(15)
_GH_W = _GH_W / _GH_W.sum()


def logit(s):
    return math.log(s / (1 - s))


def sigmoid(z):
    return 1 / (1 + math.exp(-z))


def load_games(path="vb_games.csv"):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in _INT_COLS:
            r[c] = int(r[c])
    return rows


def points(r):
    """(홈 득점, 원정 득점) — 세트별 점수 합."""
    return sum(r[f"h{i}"] for i in range(1, 6)), sum(r[f"a{i}"] for i in range(1, 6))


# ── 확률 계산 ──
def set_win_prob(p, target):
    """랠리 승률 p로 target점 선승 세트를 이길 확률 (target-1 : target-1부터 2점차)."""
    q = 1 - p
    s = sum(comb(target - 1 + k, k) * p**target * q**k for k in range(target - 1))
    deuce = comb(2 * (target - 1), target - 1) * p**(target - 1) * q**(target - 1)
    return s + deuce * p * p / (p * p + q * q)


def _score_dist_fixed(p):
    P, P5 = set_win_prob(p, 25), set_win_prob(p, 15)
    Q = 1 - P
    return {(3, 0): P**3, (3, 1): 3 * P**3 * Q, (3, 2): 6 * P * P * Q * Q * P5,
            (2, 3): 6 * P * P * Q * Q * (1 - P5), (1, 3): 3 * Q**3 * P, (0, 3): Q**3}


def score_dist(p_rally, sigma=None):
    """세트스코어 6칸 확률. sigma > 0이면 경기 컨디션 흔들림 N(0, sigma)를 로짓에 더해 평균."""
    sigma = SIGMA if sigma is None else sigma
    if sigma == 0:
        return _score_dist_fixed(p_rally)
    z = logit(p_rally)
    out = dict.fromkeys(SCORES, 0.0)
    for x, w in zip(_GH_X, _GH_W):
        for k, v in _score_dist_fixed(sigmoid(z + sigma * x)).items():
            out[k] += w * v
    return out


# ── 레이팅 ──
def team_ratings(games):
    """상대 보정 득점률 로짓 레이팅 (평균 0)과 경기 수. 세트 점수가 없는 경기는 뺌."""
    won, lost, n, opp = defaultdict(int), defaultdict(int), Counter(), defaultdict(list)
    for r in games:
        if not r["played"]:
            continue
        hp, ap = points(r)
        if hp + ap == 0:
            continue
        h, a = r["home"], r["away"]
        won[h] += hp; lost[h] += ap; won[a] += ap; lost[a] += hp
        n[h] += 1; n[a] += 1
        opp[h].append(a); opp[a].append(h)
    if not n:
        return {}, Counter()
    raw = {t: logit(won[t] / (won[t] + lost[t])) for t in n}
    r = dict(raw)
    for _ in range(20):
        r = {t: raw[t] + sum(r[o] for o in opp[t]) / len(opp[t]) for t in n}
        m = sum(r.values()) / len(r)
        r = {t: v - m for t, v in r.items()}
    return r, n


def home_logit(games):
    """홈팀 랠리 득점률의 로짓 (홈 이점)."""
    hp = ap = 0
    for r in games:
        if r["played"]:
            h, a = points(r)
            hp += h; ap += a
    return logit(hp / (hp + ap)) if hp + ap else 0.0


def blend(cur, n, prior):
    w = n / (n + K)
    return w * cur + (1 - w) * REGRESS * prior
