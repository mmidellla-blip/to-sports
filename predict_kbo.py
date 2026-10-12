"""
KBO 득점 예측기 (야구토토 스페셜 득점대용)

사용법
  python predict_kbo.py --date 20261013                       # 그날 경기 전부 (예고 선발 자동)
  python predict_kbo.py --home LG --away SSG --home-sp 치리노스 --away-sp 화이트
  python predict_kbo.py --backtest --season 2026              # 시즌 백테스트 (경기 전날까지 데이터만 사용)

데이터: kbo_games.csv (python kbo_scores.py 로 수집)

계산 방식 (경기마다)
  1. 타선   = 팀 경기당 득점. 이번 시즌 n경기를 n/(n+TEAM_K) 만큼 믿고, 나머지는 지난 시즌(평균 회귀) 값.
  2. 선발   = 그 투수가 선발로 나온 경기의 팀 실점. 등판 s번을 s/(s+SP_K) 만큼 믿고, 나머지는 팀 실점.
  3. 구장   = 그 구장 경기당 총득점 ÷ 리그 평균. g경기를 g/(g+PARK_K) 만큼 믿어요.
  4. 예상 득점 = 리그평균 × (타선/리그) × (상대 선발 실점/리그) × 구장 × 홈 보정
  5. 득점대 확률 = 음이항분포(평균 = 예상 득점, 흩어짐 = DISPERSION)
"""
import argparse
import csv
import math
import pathlib
import sys
from collections import defaultdict
from datetime import date, datetime

# ── 설정값 ───────────────────────────────────────────────────────────
TEAM_K = 60          # 이번 시즌 경기가 이만큼 쌓이면 지난 시즌과 반반 (2026 백테스트로 맞춤)
KEEP_LAST = 0.2      # 지난 시즌 팀 득점·실점이 리그 평균과 다른 정도 중 다음 시즌에 남는 비율
SP_K = 15            # 선발 등판이 이만큼 쌓이면 팀 실점과 반반
PARK_K = 120         # 구장 보정을 믿는 속도 (구장 경기 수)
HOME_ADV = 0.97      # 홈팀 득점 배수. 1보다 작은 건 이기는 홈팀이 9회말을 안 하기 때문 (2025·2026 백테스트)
DISPERSION = 3.5     # 음이항 r. 작을수록 점수가 크게 흩어짐 (2025·2026 백테스트)
FIVE_RATIO = None    # 5회까지 득점 비율. None이면 데이터에서 계산
CAL = 1.04           # 전체 득점 보정. 선발 보정이 점수를 ~4% 낮게 잡는 걸 바로잡음 (2025로 정하고 2026으로 검증)

BINS = [(0, 1, "0~1"), (2, 3, "2~3"), (4, 5, "4~5"), (6, 7, "6~7"), (8, 9, "8~9"), (10, 99, "10+")]
# ────────────────────────────────────────────────────────────────────


def load(path="kbo_games.csv"):
    p = pathlib.Path(path)
    if not p.exists():
        sys.exit(f"{path} 이 없어요. 먼저 python kbo_scores.py --season 2025 로 수집하세요.")
    with p.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["season"] = int(r["season"])
        r["home_final"], r["away_final"] = int(r["home_final"]), int(r["away_final"])
        for k in ("home_5", "away_5"):
            r[k] = int(r[k]) if r[k] not in ("", None) else None
    return rows


class State:
    """어떤 날짜 '전까지'의 경기만으로 만든 팀·투수·구장 통계."""

    def __init__(self, games, season, before=None):
        cur = [g for g in games if g["season"] == season and (before is None or g["date"] < before)]
        last = [g for g in games if g["season"] == season - 1]
        self.n_cur = len(cur)

        def league(gs):
            return sum(g["home_final"] + g["away_final"] for g in gs) / (2 * len(gs)) if gs else None

        self.lg_last = league(last)
        self.lg = league(cur) if len(cur) >= 50 else None
        if self.lg is None:
            # 시즌 초: 지금까지 경기와 지난 시즌을 경기 수로 섞음
            base = self.lg_last or 4.8
            n = 2 * len(cur)
            self.lg = (sum(g["home_final"] + g["away_final"] for g in cur) + base * 100) / (n + 100) if cur else base

        five = [g for g in cur + last if g["home_5"] is not None]
        self.five_ratio = FIVE_RATIO or (
            sum(g["home_5"] + g["away_5"] for g in five) / sum(g["home_final"] + g["away_final"] for g in five)
            if len(five) >= 50 else 0.56)

        def team_table(gs):
            t = defaultdict(lambda: [0, 0, 0])  # 경기수, 득점, 실점
            for g in gs:
                for side, opp in (("home", "away"), ("away", "home")):
                    x = t[g[side]]
                    x[0] += 1
                    x[1] += g[f"{side}_final"]
                    x[2] += g[f"{opp}_final"]
            return t

        self.cur_t, self.last_t = team_table(cur), team_table(last)

        # 선발 투수: 이번 시즌 + 지난 시즌(절반 가중) 선발 경기의 팀 실점
        self.sp = defaultdict(lambda: [0.0, 0.0])  # 가중 등판 수, 가중 실점 합
        for gs, w in ((cur, 1.0), (last, 0.5)):
            for g in gs:
                for side, opp in (("home", "away"), ("away", "home")):
                    name = g[f"{side}_sp"]
                    if name:
                        key = (g[side], name)
                        self.sp[key][0] += w
                        self.sp[key][1] += w * g[f"{opp}_final"]

        # 구장: 이번 시즌 + 지난 시즌 경기당 총득점
        park = defaultdict(lambda: [0, 0])
        for g in cur + last:
            park[g["stadium"]][0] += 1
            park[g["stadium"]][1] += g["home_final"] + g["away_final"]
        all_lg = league(cur + last) or self.lg
        self.park = {s: (n / (n + PARK_K)) * (r / n / (2 * all_lg)) + (PARK_K / (n + PARK_K)) for s, (n, r) in park.items()}
        self.home_park = {}
        for g in cur + last:
            self.home_park.setdefault(g["home"], defaultdict(int))[g["stadium"]] += 1

    def team(self, name):
        """(득점/경기, 실점/경기) — 지난 시즌을 평균 회귀시킨 뒤 이번 시즌과 섞음."""
        lg = self.lg
        if name in self.last_t and self.lg_last:
            n, s, a = self.last_t[name]
            prior_s = lg + KEEP_LAST * (s / n - self.lg_last)
            prior_a = lg + KEEP_LAST * (a / n - self.lg_last)
        else:
            prior_s = prior_a = lg
        n, s, a = self.cur_t.get(name, (0, 0, 0))
        w = n / (n + TEAM_K)
        return (w * (s / n if n else 0) + (1 - w) * prior_s,
                w * (a / n if n else 0) + (1 - w) * prior_a)

    def starter(self, team, name):
        """그 선발이 나온 경기의 팀 실점 (등판 적으면 팀 실점 쪽으로)."""
        team_ra = self.team(team)[1]
        if not name:
            return team_ra, 0
        n, ra = self.sp.get((team, name), (0, 0))
        w = n / (n + SP_K)
        return w * (ra / n if n else 0) + (1 - w) * team_ra, n

    def default_park(self, home):
        parks = self.home_park.get(home)
        return max(parks, key=parks.get) if parks else None


def nb_pmf(k, mu, r):
    p = r / (r + mu)
    return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1) + r * math.log(p) + k * math.log(1 - p))


def bin_probs(mu, r=None):
    r = r or DISPERSION
    pm = [nb_pmf(k, mu, r) for k in range(60)]
    return [sum(pm[lo:min(hi, 59) + 1]) for lo, hi, _ in BINS]


def predict(st, home, away, home_sp=None, away_sp=None, stadium=None):
    stadium = stadium or st.default_park(home)
    hs, _ = st.team(home)
    as_, _ = st.team(away)
    h_sp_ra, h_n = st.starter(home, home_sp)
    a_sp_ra, a_n = st.starter(away, away_sp)
    park = st.park.get(stadium, 1.0)
    lg = st.lg
    mu_h = lg * (hs / lg) * (a_sp_ra / lg) * park * HOME_ADV * CAL
    mu_a = lg * (as_ / lg) * (h_sp_ra / lg) * park / HOME_ADV * CAL
    return {"home": home, "away": away, "home_sp": home_sp, "away_sp": away_sp, "stadium": stadium,
            "park": park, "home_sp_n": h_n, "away_sp_n": a_n, "mu_home": mu_h, "mu_away": mu_a,
            "home_bins": bin_probs(mu_h), "away_bins": bin_probs(mu_a),
            "home_bins5": bin_probs(mu_h * st.five_ratio), "away_bins5": bin_probs(mu_a * st.five_ratio)}


def to_bin(x):
    for i, (lo, hi, _) in enumerate(BINS):
        if lo <= x <= hi:
            return i


def pick(team, probs, lab):
    """확률 1위 득점대. 2위와 3%p 이내로 비슷하면 같이 적어요 (복식 후보)."""
    order = sorted(range(len(probs)), key=lambda i: -probs[i])
    a, b = order[0], order[1]
    s = f"{team} {lab[a]}점 ({probs[a] * 100:.0f}%)"
    if probs[a] - probs[b] < 0.03:
        s += f" ≈ {lab[b]}점 ({probs[b] * 100:.0f}%)"
    return s


def show(p, five=False):
    lab = [b[2] for b in BINS]
    print(f"\n=== {p['home']} (홈) vs {p['away']} (원정)  @{p['stadium']} (구장 보정 x{p['park']:.2f}) ===")
    print(f"선발: {p['home']} {p['home_sp'] or '미정'} ({p['home_sp_n']:.0f}등판 반영) / "
          f"{p['away']} {p['away_sp'] or '미정'} ({p['away_sp_n']:.0f}등판 반영)")
    print(f"평균 득점(참고용, 고를 칸 아님): {p['home']} {p['mu_home']:.2f}  vs  {p['away']} {p['mu_away']:.2f}")
    for tag, hk, ak in (("최종", "home_bins", "away_bins"),) + ((("5회", "home_bins5", "away_bins5"),) if five else ()):
        print(f"▶ [{tag}] 고를 득점대: {pick(p['home'], p[hk], lab)}  /  {pick(p['away'], p[ak], lab)}")
        print(f"[{tag}] 득점대   " + "  ".join(f"{l:>5}" for l in lab))
        print(f"  {p['home']:<6}" + "  ".join(f"{x * 100:4.0f}%" for x in p[hk]))
        print(f"  {p['away']:<6}" + "  ".join(f"{x * 100:4.0f}%" for x in p[ak]))
        combos = sorted(((p[hk][i] * p[ak][j], i, j) for i in range(len(BINS)) for j in range(len(BINS))), reverse=True)[:3]
        print("  확률 높은 조합: " + " / ".join(f"{p['home']} {lab[i]}·{p['away']} {lab[j]} {pr * 100:.1f}%" for pr, i, j in combos))


def today_games(day):
    """KBO 사이트에서 그날 경기와 예고 선발을 받아요."""
    import kbo_scores
    d = kbo_scores.post("Main.asmx/GetKboGameList", {"leId": 1, "srId": "0,1,3,4,5,7,9", "date": day})
    return [(g["HOME_NM"], g["AWAY_NM"], (g["B_PIT_P_NM"] or "").strip(), (g["T_PIT_P_NM"] or "").strip(), g["S_NM"])
            for g in d.get("game", []) if str(g["CANCEL_SC_ID"]) == "0"]


def backtest(games, season, quiet=False, start_after=0):
    """경기 전날까지 데이터만으로 예측 → 실제와 비교. 기준(리그 평균만 쓴 예측)과 로그손실 비교."""
    gs = sorted([g for g in games if g["season"] == season], key=lambda g: g["date"])
    by_date = defaultdict(list)
    for g in gs:
        by_date[g["date"]].append(g)
    n = ae = ll = ll_base = hit = 0
    for day in sorted(by_date):
        st = State(games, season, before=day)
        if st.n_cur < start_after:
            continue
        for g in by_date[day]:
            p = predict(st, g["home"], g["away"], g["home_sp"], g["away_sp"], g["stadium"])
            base = bin_probs(st.lg)
            for side in ("home", "away"):
                y = g[f"{side}_final"]
                b = to_bin(y)
                probs = p[f"{side}_bins"]
                n += 1
                ae += abs(p[f"mu_{side}"] - y)
                ll += -math.log(max(probs[b], 1e-9))
                ll_base += -math.log(max(base[b], 1e-9))
                hit += probs.index(max(probs)) == b
    if not quiet:
        print(f"{season} 시즌 {n // 2}경기 백테스트 (팀 득점 {n}개)")
        print(f"  평균 오차        : {ae / n:.2f}점")
        print(f"  최다확률 득점대 적중: {hit / n * 100:.1f}%")
        print(f"  로그손실         : 모델 {ll / n:.4f}  vs  리그평균만 {ll_base / n:.4f}  "
              f"({'모델이 나음' if ll < ll_base else '모델이 못함'}, 낮을수록 좋음)")
    return ae / n, ll / n, ll_base / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="kbo_games.csv")
    ap.add_argument("--home"); ap.add_argument("--away")
    ap.add_argument("--home-sp"); ap.add_argument("--away-sp")
    ap.add_argument("--stadium")
    ap.add_argument("--date", help="YYYYMMDD: 그날 경기 전부 예측 (예고 선발 자동)")
    ap.add_argument("--season", type=int)
    ap.add_argument("--five", action="store_true", help="5회까지 득점대도 보기")
    ap.add_argument("--backtest", action="store_true")
    args = ap.parse_args()

    games = load(args.data)
    season = args.season or max(g["season"] for g in games)

    if args.backtest:
        backtest(games, season)
        return

    if args.date:
        day_iso = datetime.strptime(args.date, "%Y%m%d").date().isoformat()
        st = State(games, season, before=day_iso)
        for home, away, hsp, asp, park in today_games(args.date):
            show(predict(st, home, away, hsp, asp, park), args.five)
        return

    if not (args.home and args.away):
        ap.error("--date 또는 --home/--away 를 지정하세요")
    st = State(games, season)
    show(predict(st, args.home, args.away, args.home_sp, args.away_sp, args.stadium), args.five)


if __name__ == "__main__":
    main()
