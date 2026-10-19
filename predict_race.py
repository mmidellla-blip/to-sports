"""
경마 1착 확률 예측기 (조건부 로짓 + 시장 배당 결합, Benter 방식)

사용법
  python predict_race.py --backtest                          # 앞 70% 경주로 학습, 뒤 30%로 검증
  python predict_race.py --backtest --test-from 20260101     # 이 날짜부터 검증
  python predict_race.py --race 20261012 --meet 1            # 그날 서울 경주 전부 (그 전날까지 데이터로 학습)
  python predict_race.py --race 20261012 --meet 1 --no 5     # 5경주만

데이터: kra_races.csv (python kra_races.py 로 수집)

계산 방식
  1. 말마다 경주 전날까지의 기록으로 특징을 만들어요 (같은 날 결과는 안 씀)
       최근 폼   = 최근 5경주 성적점수(1착 1.0 ~ 꼴찌 0.0), 최근일수록 크게. 경주 수가 적으면 0.5 쪽으로 당김
       승률      = 1착 횟수 / 출전 수 (적으면 평균 쪽으로 당김)
       경험      = log(출전 수 + 1), 첫 출전 여부
       휴식      = 지난 경주 후 지난 날 수 (log)
       기수·조교사 = 1착률 (출전이 적으면 평균 쪽으로 당김)
       부담중량·레이팅 = 그 경주 평균과의 차이
       마체중 증감 크기, 게이트 위치, 평소 뛰던 거리와 차이
  2. 모델 점수 = 특징 × 가중치, 1착 확률 = 그 경주 안에서 softmax (경주마다 확률 합 100%)
     가중치는 학습 기간에 '실제 1착 말의 확률'이 가장 높아지게 맞춰요 (조건부 로짓, 뉴턴법)
  3. 시장 확률 = (1/단승배당)을 그 경주 합이 100%가 되게 나눈 것 (마사회 몫이 빠진 확률)
  4. 결합 확률 = softmax(a × log 모델 + b × log 시장). a, b 도 학습 기간에서 맞춰요.
     Benter: "모델만으로는 시장을 못 이긴다. 시장에 없는 정보를 얹어야 한다"
  5. 기대값 = 결합 확률 × 단승 배당. 1보다 크면 이론상 이득인 베팅

주의
  - 결과 파일의 단승 배당은 '마감 배당'이에요. 실제로 베팅할 때 본 배당과 조금 달라요.
  - 마사회 몫(약 20~30%)을 넘어야 수익이 나요. 백테스트에서 시장보다 로그손실이 낮아도 수익은 다른 문제예요.
"""
import argparse
import csv
import math
import pathlib
import sys
from collections import defaultdict
from datetime import date, datetime

import numpy as np

# ── 설정값 ───────────────────────────────────────────────────────────
FORM_N = 5           # 최근 폼에 쓰는 경주 수
FORM_DECAY = 0.75    # 한 경주 전으로 갈 때마다 곱하는 가중치
FORM_K = 1.5         # 폼: 경주 가중치 합이 이만큼이면 0.5와 반반
WIN_K = 5            # 말 승률: 출전이 이만큼이면 평균과 반반
PERSON_K = 60        # 기수·조교사 1착률: 출전이 이만큼이면 평균과 반반
RIDGE = 1.0          # 가중치 크기 벌점 (과적합 방지)
MIN_FIELD = 5        # 출전 말이 이보다 적은 경주는 학습에서 뺌
TRAIN_SHARE = 0.7    # --test-from 이 없을 때 학습에 쓰는 경주 비율
EDGE = 1.10          # 기대값이 이보다 크면 백테스트에서 단승 1단위 베팅
MEET_NAMES = {"1": "서울", "2": "제주", "3": "부경", "4": "영천"}
# ────────────────────────────────────────────────────────────────────

FEATURES = [
    ("form", "최근 폼"),
    ("last", "직전 경주 성적"),
    ("win", "말 승률"),
    ("exp", "경험(출전 수)"),
    ("debut", "첫 출전"),
    ("rest", "휴식 기간"),
    ("jockey", "기수 1착률"),
    ("trainer", "조교사 1착률"),
    ("burden", "부담중량(경주 평균 대비)"),
    ("rating", "레이팅(경주 평균 대비)"),
    ("wt_jump", "마체중 증감 크기"),
    ("gate", "게이트 위치"),
    ("dist_gap", "평소 거리와 차이"),
]


def fnum(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load(path):
    p = pathlib.Path(path)
    if not p.exists():
        sys.exit(f"{path} 이 없어요. 먼저 python kra_races.py --from 20240101 로 수집하세요.")
    with p.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    races = defaultdict(list)
    for r in rows:
        if int(fnum(r["finish"], 0)) <= 0:      # 취소·제외·실격
            continue
        races[(r["date"], r["meet"], int(fnum(r["rc_no"], 0)))].append(r)
    return dict(sorted(races.items()))


def score(finish, field):
    """1착 1.0 ~ 꼴찌 0.0"""
    return 1.0 - (finish - 1) / max(field - 1, 1)


class History:
    """경주 전날까지의 말·기수·조교사 기록"""

    def __init__(self):
        self.horse = defaultdict(list)          # (date, score, won, dist)
        self.jockey = defaultdict(lambda: [0, 0])
        self.trainer = defaultdict(lambda: [0, 0])
        self.wins = 0
        self.starts = 0

    def base(self):
        return self.wins / self.starts if self.starts else 0.1

    def features(self, race):
        d = datetime.strptime(race[0]["date"], "%Y-%m-%d").date()
        field = len(race)
        base = self.base()
        burdens = [fnum(r["burden"]) for r in race if fnum(r["burden"]) is not None]
        ratings = [fnum(r["rating"]) for r in race if fnum(r["rating"])]
        mb = sum(burdens) / len(burdens) if burdens else 0
        mr = sum(ratings) / len(ratings) if ratings else 0
        dist = fnum(race[0]["dist"], 0)
        out = []
        for r in race:
            past = self.horse[r["horse_no"] or r["horse"]]
            n = len(past)
            recent = past[-FORM_N:][::-1]
            ws = [FORM_DECAY ** i for i in range(len(recent))]
            form = (sum(w * p[1] for w, p in zip(ws, recent)) + FORM_K * 0.5) / (sum(ws) + FORM_K)
            wins = sum(p[2] for p in past)
            jk = self.jockey[r["jockey_no"] or r["jockey"]]
            tr = self.trainer[r["trainer_no"] or r["trainer"]]
            dists = [p[3] for p in past if p[3]]
            b, rt, wc, g = fnum(r["burden"]), fnum(r["rating"]), fnum(r["wt_change"]), fnum(r["gate"])
            out.append([
                form,
                past[-1][1] if past else 0.5,
                (wins + WIN_K * base) / (n + WIN_K),
                math.log1p(n),
                1.0 if n == 0 else 0.0,
                math.log1p(min((d - past[-1][0]).days, 365)) if past else 0.0,
                (jk[0] + PERSON_K * base) / (jk[1] + PERSON_K),
                (tr[0] + PERSON_K * base) / (tr[1] + PERSON_K),
                (b - mb) if b is not None else 0.0,
                (rt - mr) if rt else 0.0,
                abs(wc) if wc is not None else 0.0,
                (g - 1) / max(field - 1, 1) if g else 0.5,
                abs(dist - sum(dists) / len(dists)) / 100 if dists and dist else 0.0,
            ])
        return out

    def update(self, race):
        d = datetime.strptime(race[0]["date"], "%Y-%m-%d").date()
        field = len(race)
        dist = fnum(race[0]["dist"], 0)
        for r in race:
            fin = int(fnum(r["finish"]))
            won = 1 if fin == 1 else 0
            self.horse[r["horse_no"] or r["horse"]].append((d, score(fin, field), won, dist))
            for book, k in ((self.jockey, r["jockey_no"] or r["jockey"]), (self.trainer, r["trainer_no"] or r["trainer"])):
                book[k][0] += won
                book[k][1] += 1
            self.wins += won
            self.starts += 1


def build(races, until=None):
    """경주마다 (key, 말들, 특징) 를 날짜 순으로. until 날짜 전까지만 기록에 반영."""
    hist = History()
    out = []
    by_date = defaultdict(list)
    for k, race in races.items():
        by_date[k[0]].append((k, race))
    for d in sorted(by_date):
        if until and d > until:
            break
        todays = [(k, race, hist.features(race)) for k, race in by_date[d]]
        out += todays
        for _, race, _ in todays:   # 같은 날 결과는 다음 날부터 반영
            hist.update(race)
    return out


# ── 조건부 로짓 ─────────────────────────────────────────────────────

def stack(items):
    """경주 리스트 → X, 승자 표시 y, 경주 시작 위치"""
    X, y, starts = [], [], []
    for feats, winners in items:
        starts.append(len(X))
        X += feats
        y += winners
    return np.array(X, float), np.array(y, float), np.array(starts)


def race_softmax(s, starts):
    counts = np.diff(np.append(starts, len(s)))
    mx = np.repeat(np.maximum.reduceat(s, starts), counts)
    e = np.exp(s - mx)
    return e / np.repeat(np.add.reduceat(e, starts), counts)


def fit_logit(X, y, starts, ridge=RIDGE, iters=30):
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = race_softmax(X @ w, starts)
        g = X.T @ (y - p) - ridge * w
        m = np.add.reduceat(p[:, None] * X, starts)
        H = -(X.T @ (p[:, None] * X) - m.T @ m) - ridge * np.eye(len(w))
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


class Model:
    def fit(self, train):
        items = [(f, [1.0 if int(fnum(r["finish"])) == 1 else 0.0 for r in race])
                 for _, race, f in train if usable(race)]
        X, y, starts = stack(items)
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        self.w = fit_logit((X - self.mu) / self.sd, y, starts)
        # 결합 가중치: 시장 배당이 있는 경주만
        rows = []
        for _, race, f in train:
            q = market(race)
            if q is None or not usable(race):
                continue
            p = self.prob(f)
            rows.append((np.column_stack([np.log(p), np.log(q)]).tolist(),
                         [1.0 if int(fnum(r["finish"])) == 1 else 0.0 for r in race]))
        if len(rows) >= 50:
            Xc, yc, sc = stack(rows)
            self.ab = fit_logit(Xc, yc, sc, ridge=0.0)
        else:
            self.ab = None
        return self

    def prob(self, feats):
        X = (np.array(feats, float) - self.mu) / self.sd
        return race_softmax(X @ self.w, np.array([0]))

    def combined(self, feats, q):
        p = self.prob(feats)
        if q is None or self.ab is None:
            return p
        s = self.ab[0] * np.log(p) + self.ab[1] * np.log(q)
        return race_softmax(s, np.array([0]))


def usable(race):
    return len(race) >= MIN_FIELD and sum(int(fnum(r["finish"])) == 1 for r in race) == 1


def market(race):
    odds = [fnum(r["win_odds"], 0) for r in race]
    # 9999.9 는 발매가 없었던 경주에 붙는 자리표시 값이에요
    if any(o <= 1.0 or o >= 9999 for o in odds):
        return None
    inv = np.array([1 / o for o in odds])
    return inv / inv.sum()


# ── 실행 ──────────────────────────────────────────────────────────────

def backtest(races, test_from):
    built = build(races)
    keys = [k for k, _, _ in built]
    if not test_from:
        test_from = keys[int(len(keys) * TRAIN_SHARE)][0]
    train = [b for b in built if b[0][0] < test_from]
    test = [b for b in built if b[0][0] >= test_from and usable(b[1])]
    if len(train) < 200 or not test:
        sys.exit(f"경주가 부족해요 (학습 {len(train)}, 검증 {len(test)}). 더 긴 기간을 수집하세요.")
    m = Model().fit(train)

    print(f"학습: {train[0][0][0]} ~ {train[-1][0][0]}  경주 {len(train)}개")
    print(f"검증: {test[0][0][0]} ~ {test[-1][0][0]}  경주 {len(test)}개\n")

    print("가중치 (표준화한 특징 1단위당 점수, +면 1착 확률을 올림)")
    for (_, name), w in sorted(zip(FEATURES, m.w), key=lambda t: -abs(t[1])):
        print(f"  {name:<22}{w:+.3f}")
    if m.ab is not None:
        print(f"\n결합: {m.ab[0]:.2f} × log 모델 + {m.ab[1]:.2f} × log 시장")

    ll = defaultdict(float)
    hit = defaultdict(int)
    n_mkt, overround = 0, 0.0
    bets, ret, fav_ret, cal = 0, 0.0, 0.0, defaultdict(lambda: [0.0, 0, 0])
    for _, race, f in test:
        win = [int(fnum(r["finish"])) == 1 for r in race].index(True)
        p = m.prob(f)
        ll["균등"] += math.log(len(race))
        ll["모델"] -= math.log(p[win])
        hit["모델"] += int(np.argmax(p) == win)
        q = market(race)
        if q is None:
            continue
        odds = np.array([fnum(r["win_odds"]) for r in race])
        c = m.combined(f, q)
        n_mkt += 1
        overround += (1 / odds).sum()
        for name, pr in (("모델(배당 있는 경주)", p), ("시장", q), ("결합", c)):
            ll[name] -= math.log(pr[win])
            hit[name] += int(np.argmax(pr) == win)
        fav = int(np.argmin(odds))
        fav_ret += odds[fav] if fav == win else 0.0
        for i, (pi, oi) in enumerate(zip(c, odds)):
            b = min(int(pi * 10), 9)
            cal[b][0] += pi
            cal[b][1] += 1
            cal[b][2] += int(i == win)
            if pi * oi > EDGE:
                bets += 1
                ret += oi if i == win else 0.0

    n = len(test)
    print(f"\n검증 결과 (경주당 로그손실, 낮을수록 좋음)")
    print(f"  균등(아무 정보 없음)      {ll['균등'] / n:.4f}   전체 {n}경주")
    print(f"  모델                    {ll['모델'] / n:.4f}   1위 예측 적중 {hit['모델'] / n:.1%}")
    if n_mkt:
        print(f"  ── 배당 있는 {n_mkt}경주 ──")
        for name in ("모델(배당 있는 경주)", "시장", "결합"):
            print(f"  {name:<20}{ll[name] / n_mkt:.4f}   1위 예측 적중 {hit[name] / n_mkt:.1%}")
        print(f"\n  시장 1/배당 합 평균 {overround / n_mkt:.3f} → 마사회 몫 약 {1 - n_mkt / overround:.1%}")
        print(f"  인기 1위 말에 매번 단승 1단위: 회수율 {fav_ret / n_mkt:.1%}")
        if bets:
            print(f"  결합 기대값 > {EDGE} 인 말에 단승 1단위: {bets}번 베팅, 회수율 {ret / bets:.1%}")
        else:
            print(f"  결합 기대값 > {EDGE} 인 말이 없었어요")
        print("\n  보정 확인 (결합 확률 구간별 예측 vs 실제 1착률)")
        for b in sorted(cal):
            s, cnt, w = cal[b]
            if cnt >= 30:
                print(f"    {b * 10:>2}~{b * 10 + 10}%  말 {cnt:>5}  예측 {s / cnt:5.1%}  실제 {w / cnt:5.1%}")
        if (ll["시장"] - ll["결합"]) / n_mkt < 0.005:
            print("\n  → 결합과 시장 차이가 0.005 미만이에요: 사실상 같아요. 모델이 배당 이상의 정보를 못 주고 있어요.")
        elif ll["결합"] < ll["시장"]:
            print("\n  → 결합이 시장보다 로그손실이 낮아요: 모델이 배당에 없는 정보를 조금 갖고 있다는 뜻이에요.")
        else:
            print("\n  → 결합이 시장보다 낫지 않아요: 지금 특징으로는 배당 이상의 정보가 없어요.")
    print("  (회수율 100% 미만 = 손실. 마감 배당 기준이라 실제와 다를 수 있어요)")


def predict(races, day, meet, no):
    built = build(races, until=day)
    train = [b for b in built if b[0][0] < day]
    target = [b for b in built if b[0][0] == day and (not meet or b[0][1] == meet) and (not no or b[0][2] == no)]
    if not target:
        sys.exit(f"{day} 경주가 kra_races.csv 에 없어요. (아직 안 열린 경주는 출전표 수집이 필요해요)")
    m = Model().fit(train)
    print(f"학습: {train[0][0][0]} ~ {train[-1][0][0]}  경주 {len(train)}개 (그 전날까지만 사용)")
    for (d, mt, rno), race, f in target:
        q = market(race)
        p = m.prob(f)
        c = m.combined(f, q)
        print(f"\n=== {d} {MEET_NAMES.get(mt, mt)} {rno}경주  {race[0]['dist']}m {race[0]['grade']} {race[0]['track']} ===")
        print(f"  {'번':>2} {'마명':<10} {'기수':<6} {'모델':>6} {'시장':>6} {'결합':>6} {'배당':>6} {'기대값':>6}  실제")
        order = np.argsort(-c)
        for i in order:
            r = race[i]
            o = fnum(r["win_odds"])
            mk = f"{q[i]:6.1%}" if q is not None else "     -"
            ev = f"{c[i] * o:6.2f}" if o else "     -"
            od = f"{o:6.1f}" if o else "     -"
            star = " ★" if o and c[i] * o > EDGE else ""
            print(f"  {r['gate']:>2} {r['horse'][:10]:<10} {r['jockey'][:6]:<6} {p[i]:6.1%} {mk} {c[i]:6.1%} {od} {ev}  {r['finish']}착{star}")
    print(f"\n★ = 결합 기대값 > {EDGE}. 배당은 결과 파일의 마감 배당이에요.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="kra_races.csv")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--test-from", help="검증 시작일 YYYYMMDD")
    ap.add_argument("--race", help="예측할 날짜 YYYYMMDD")
    ap.add_argument("--meet", help="경마장 코드 (1 서울, 3 부경)")
    ap.add_argument("--no", type=int, help="경주 번호")
    args = ap.parse_args()

    races = load(args.data)

    def iso(s):
        return datetime.strptime(s, "%Y%m%d").date().isoformat()

    if args.backtest:
        backtest(races, iso(args.test_from) if args.test_from else None)
    elif args.race:
        predict(races, iso(args.race), args.meet, args.no)
    else:
        ap.error("--backtest 또는 --race 를 지정하세요")


if __name__ == "__main__":
    main()
