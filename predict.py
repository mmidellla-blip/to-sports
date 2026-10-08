"""
KBL 경기 점수대 예측기 (농구토토 매치 연습용)

사용법:
    python predict.py --home 원주DB --away 창원LG
    python predict.py --home 원주DB --away 창원LG --data sample_games.csv
    python predict.py --backtest            # 지난 경기들로 내 모델 오차 확인

지난 시즌은 경기 기록 대신 last_season.csv(팀별 평균 득점·실점)만 채워도 돼요.

필요한 데이터: games.csv (한 줄 = 한 경기)
    date, season, home, away, home_half, away_half, home_final, away_final
"""

import argparse
import math
import pandas as pd

# ── 설정값: 여기를 바꿔가며 실험해 보세요 ─────────────────────────
CURRENT_SEASON = "2026-27"
LAST_SEASON = "2025-26"
HOME_ADV = 1.5        # 홈 이점(점). 데이터로 직접 구해볼 수도 있어요
BLEND_K = 5           # 이번 시즌 경기 수가 K경기쯤 쌓이면 지난 시즌과 반반 반영
HALF_RATIO = 0.48     # 기본 전반 비율 (전반 기록이 3경기 미만인 팀은 이 값을 씀)
HALF_MIN_GAMES = 3
H2H_WEIGHT = 0.25     # 상대전적(h2h.csv) 반영 비율. 0이면 상대전적 무시
LEAGUE_K = 5          # 리그 전체 득점 변화를 믿는 속도. 외국인 2명 동시기용 제도 변화가 있어 빠르게 반영
KEEP_PTS = 0.3        # 지난 시즌 '득점'이 리그 평균과 다른 정도 중 다음 시즌에 남는 비율 (3시즌 분석: 거의 0)
KEEP_OPP = 0.7        # 지난 시즌 '실점'(수비)이 남는 비율 (3시즌 분석: 0.69)
ABSENT_FACTOR = 0.5   # 결장 선수 득점 중 팀이 실제로 잃는 비율 (나머지는 다른 선수가 메움)
MARGIN_SD = 12        # 점수 차가 예측에서 보통 벗어나는 폭(가정). 확률 계산용
TOTAL_SD = 16         # 합계 점수가 예측에서 보통 벗어나는 폭(가정)

# 토토 득점대 구간 (회차마다 베트맨에서 꼭 확인!)  (하한, 상한, 이름)
HALF_BINS = [(0, 34, "34점 이하"), (35, 39, "35~39"), (40, 44, "40~44"),
             (45, 49, "45~49"), (50, 54, "50~54"), (55, 999, "55점 이상")]
FINAL_BINS = [(0, 69, "69점 이하"), (70, 79, "70~79"), (80, 89, "80~89"),
              (90, 99, "90~99"), (100, 109, "100~109"), (110, 999, "110점 이상")]  # 매치 82회차 기준
# ────────────────────────────────────────────────────────────────


def load_games(path):
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


def team_rows(df):
    """경기 1줄을 팀 관점 2줄로 펼치기 (득점/실점/전반 득점)."""
    home = pd.DataFrame({
        "date": df["date"], "season": df["season"], "team": df["home"],
        "is_home": True, "pts": df["home_final"], "opp_pts": df["away_final"],
        "half_pts": df["home_half"],
    })
    away = pd.DataFrame({
        "date": df["date"], "season": df["season"], "team": df["away"],
        "is_home": False, "pts": df["away_final"], "opp_pts": df["home_final"],
        "half_pts": df["away_half"],
    })
    return pd.concat([home, away], ignore_index=True)


PRIOR = {}  # 지난 시즌 팀 평균 (last_season.csv에서 읽음)
LEAGUE = {}  # 리그 득점 환경 보정값
H2H = {}    # 상대전적 (h2h.csv에서 읽음): (팀, 상대) -> {pts, opp_pts, games}


def load_h2h(path):
    """상대전적표: team, opp, games, pts, opp_pts. 양방향으로 등록해요."""
    try:
        h = pd.read_csv(path)
    except FileNotFoundError:
        return {}
    out = {}
    for _, r in h.iterrows():
        out[(r["team"], r["opp"])] = {"pts": r["pts"], "opp_pts": r["opp_pts"], "games": r["games"]}
        out[(r["opp"], r["team"])] = {"pts": r["opp_pts"], "opp_pts": r["pts"], "games": r["games"]}
    return out


def load_prior(path):
    """지난 시즌 팀 평균표: team, pts, opp_pts (경기 기록 대신 쓸 수 있어요)."""
    try:
        p = pd.read_csv(path).dropna(subset=["pts", "opp_pts"])
    except FileNotFoundError:
        return {}
    return {r["team"]: {"pts": r["pts"], "opp_pts": r["opp_pts"]} for _, r in p.iterrows()}


def team_profile(rows, team):
    """지난 시즌과 이번 시즌 평균을 경기 수에 따라 섞은 팀 프로필."""
    t = rows[rows["team"] == team]
    last = t[t["season"] == LAST_SEASON]
    cur = t[t["season"] == CURRENT_SEASON]

    # 지난 시즌 평균: 경기 기록이 있으면 그걸로, 없으면 평균표(PRIOR)로
    if len(last) > 0:
        last_avg = {"pts": last["pts"].mean(), "opp_pts": last["opp_pts"].mean()}
        last_src = f"경기기록 {len(last)}경기"
    elif team in PRIOR:
        # 평균 회귀: 지난 시즌 기록을 리그 평균 쪽으로 당겨서 사용
        mp = sum(p["pts"] for p in PRIOR.values()) / len(PRIOR)
        mo = sum(p["opp_pts"] for p in PRIOR.values()) / len(PRIOR)
        last_avg = {"pts": mp + KEEP_PTS * (PRIOR[team]["pts"] - mp),
                    "opp_pts": mo + KEEP_OPP * (PRIOR[team]["opp_pts"] - mo)}
        last_src = "시즌 평균표(평균회귀)"
    else:
        last_avg = None
        last_src = "없음"

    if last_avg is None and len(cur) == 0:
        raise ValueError(f"'{team}' 데이터가 없어요. 팀 이름 철자를 확인하세요.")

    n = len(cur)
    w = n / (n + BLEND_K)  # 이번 시즌 가중치 (0~1)

    def blend(col):
        if last_avg is None:
            return cur[col].mean()
        if n == 0:
            return last_avg[col]
        return (1 - w) * last_avg[col] + w * cur[col].mean()

    hv = t.dropna(subset=["half_pts"])
    half_ratio = (hv["half_pts"] / hv["pts"]).mean() if len(hv) >= HALF_MIN_GAMES else HALF_RATIO
    return {
        "pts": blend("pts"),
        "opp_pts": blend("opp_pts"),
        "half_ratio": half_ratio if pd.notna(half_ratio) else HALF_RATIO,
        "games_last": last_src,
        "games_cur": n,
        "cur_weight": w if last_avg is not None else 1.0,
    }


def to_bin(score, bins):
    s = round(score)
    for lo, hi, name in bins:
        if lo <= s <= hi:
            return name
    return "?"


def predict(rows, home, away):
    h, a = team_profile(rows, home), team_profile(rows, away)

    # 핵심 공식: (내 평균 득점 + 상대 평균 실점) / 2  ± 홈 이점
    home_final = (h["pts"] + a["opp_pts"]) / 2 + HOME_ADV
    away_final = (a["pts"] + h["opp_pts"]) / 2 - HOME_ADV

    # 상대전적 섞기: 맞대결은 홈/원정 반반이라 중립 점수로 보고 홈 이점을 다시 더해요
    hh = H2H.get((home, away))
    if hh is not None and H2H_WEIGHT > 0:
        base_h, base_a = home_final, away_final
        h2h_home = hh["pts"] + HOME_ADV
        h2h_away = hh["opp_pts"] - HOME_ADV
        home_final = (1 - H2H_WEIGHT) * base_h + H2H_WEIGHT * h2h_home
        away_final = (1 - H2H_WEIGHT) * base_a + H2H_WEIGHT * h2h_away
        print(f"\n[상대전적] {home} vs {away} {int(hh['games'])}경기: "
              f"{home} 평균 {hh['pts']:.1f}점, {away} 평균 {hh['opp_pts']:.1f}점 ({H2H_WEIGHT:.0%} 반영)")
        print(f"  상대전적 없이: {home} {base_h:.1f} vs {away} {base_a:.1f}")

    # 수동 보정: --boost "원주DB:+3" (영입 효과 등 모델이 모르는 정보를 내 판단으로 반영)
    for item in (ARGS.boost.split(",") if ARGS and ARGS.boost else []):
        t, v = item.split(":")
        v = float(v)
        if t.strip() == home:
            home_final += v
        elif t.strip() == away:
            away_final += v
        print(f"\n[수동 보정] {t.strip()} {v:+.1f}점")

    # 결장 선수 반영: --absent "창원LG:아치 굿윈"
    for team, name in parse_absent(ARGS.absent if ARGS else None):
        p = PLAYERS.get(name)
        if p is None:
            print(f"\n[결장] {team} {name}: players.csv에 없어서 반영 못 했어요")
            continue
        loss = p["pts"] * ABSENT_FACTOR
        if team == home:
            home_final -= loss
        elif team == away:
            away_final -= loss
        src = "이번 시즌" if p["season_code"] == max(v["season_code"] for v in PLAYERS.values()) else "지난 시즌"
        print(f"\n[결장] {team} {name} ({src} 평균 {p['pts']}점) → {team} -{loss:.1f}점")

    # 리그 전체 득점 환경 보정: 이번 시즌 경기들의 평균 득점이 지난 시즌보다 높으면 그만큼 올림
    league_adj = LEAGUE.get("adj", 0.0)
    if league_adj:
        home_final += league_adj
        away_final += league_adj
        print(f"\n[리그 득점 환경] 이번 시즌 {LEAGUE['n']}경기 팀당 평균 {LEAGUE['cur']:.1f}점 "
              f"vs 지난 시즌 {LEAGUE['last']:.1f}점 → 팀당 {league_adj:+.1f}점 보정")

    home_half = home_final * h["half_ratio"]
    away_half = away_final * a["half_ratio"]

    print(f"\n=== {home} (홈) vs {away} (원정) ===")
    for name, p in [(home, h), (away, a)]:
        print(f"[{name}] 지난시즌 {p['games_last']} / 이번시즌 {p['games_cur']}경기 "
              f"(이번시즌 반영 {p['cur_weight']:.0%}) → "
              f"평균 득점 {p['pts']:.1f}, 실점 {p['opp_pts']:.1f}")

    print("\n예상 점수")
    print(f"  전반: {home} {home_half:.1f}  vs  {away} {away_half:.1f}")
    print(f"  최종: {home} {home_final:.1f}  vs  {away} {away_final:.1f}")
    print("\n예상 득점대")
    print(f"  전반: {home} {to_bin(home_half, HALF_BINS)} / {away} {to_bin(away_half, HALF_BINS)}")
    print(f"  최종: {home} {to_bin(home_final, FINAL_BINS)} / {away} {to_bin(away_final, FINAL_BINS)}")
    market_view(home, away, home_final, away_final)
    return home_final, away_final


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def market_view(home, away, hf, af):
    """예측 점수를 확률로 바꿔 프로토 게임별로 보여주기 (정규분포 근사)."""
    m, tot = hf - af, hf + af
    p_home = 1 - ncdf((0 - m) / MARGIN_SD)
    p_h6 = 1 - ncdf((5.5 - m) / MARGIN_SD)
    p_a6 = ncdf((-5.5 - m) / MARGIN_SD)
    print("\n다른 게임으로 보면 (확률은 가정 기반 근사치)")
    print(f"  승패      : {home} 승 {p_home:.0%} / {away} 승 {1-p_home:.0%}")
    print(f"  승5패     : {home} 6점차+ {p_h6:.0%} / 5점 이내 {1-p_h6-p_a6:.0%} / {away} 6점차+ {p_a6:.0%}")
    if ARGS.hcp is not None:
        p = 1 - ncdf((-ARGS.hcp - m) / MARGIN_SD)
        print(f"  핸디캡 {ARGS.hcp:+}: 승 {p:.0%} / 패 {1-p:.0%}")
    if ARGS.total is not None:
        p = 1 - ncdf((ARGS.total - tot) / TOTAL_SD)
        print(f"  언더오버 {ARGS.total}: 예측 합계 {tot:.1f} → 오버 {p:.0%} / 언더 {1-p:.0%}")


ARGS = None
PLAYERS = {}


def load_players(path):
    """선수별 평균 득점. 이번 시즌 3경기 이상이면 이번 시즌, 아니면 지난 시즌 기록을 써요.
    팀을 옮긴 선수도 이름으로 찾을 수 있게 이름 기준으로도 저장해요."""
    try:
        p = pd.read_csv(path)
    except FileNotFoundError:
        return {}
    out = {}
    for name, grp in p.sort_values("season_code").groupby("name"):
        latest = grp.iloc[-1]
        use = latest if latest["games"] >= 3 or len(grp) == 1 else grp.iloc[-2]
        info = {"pts": use["pts"], "games": use["games"], "season_code": use["season_code"],
                "team_now": latest["team"]}
        out[name] = info
    return out


def parse_absent(text):
    if not text:
        return []
    out = []
    for item in text.split(","):
        if ":" in item:
            t, n = item.split(":", 1)
            out.append((t.strip(), n.strip()))
    return out


def backtest(df, quiet=False):
    """이미 끝난 이번 시즌 경기들을, 그 경기 전 데이터만으로 예측해 보고 오차를 잰다."""
    cur = df[df["season"] == CURRENT_SEASON]
    errors, hits = [], 0
    for _, g in cur.iterrows():
        past = df[df["date"] < g["date"]]
        try:
            rows = team_rows(past)
            h, a = team_profile(rows, g["home"]), team_profile(rows, g["away"])
        except ValueError:
            continue
        ph = (h["pts"] + a["opp_pts"]) / 2 + HOME_ADV
        pa = (a["pts"] + h["opp_pts"]) / 2 - HOME_ADV
        # 리그 득점 환경 보정도 '그 경기 전' 이번 시즌 경기만으로 계산 (답지 안 보기)
        prev = past[past["season"] == CURRENT_SEASON]
        if len(PRIOR) and len(prev):
            cur_avg = (prev["home_final"].mean() + prev["away_final"].mean()) / 2
            last_avg = sum(p["pts"] for p in PRIOR.values()) / len(PRIOR)
            adj = (cur_avg - last_avg) * len(prev) / (len(prev) + LEAGUE_K)
            ph += adj
            pa += adj
        err = (abs(ph - g["home_final"]) + abs(pa - g["away_final"])) / 2
        errors.append(err)
        hit = (to_bin(ph, FINAL_BINS) == to_bin(g["home_final"], FINAL_BINS)
               and to_bin(pa, FINAL_BINS) == to_bin(g["away_final"], FINAL_BINS))
        hits += hit
        if not quiet:
          print(f"{g['date'].date()} {g['home']} vs {g['away']}: "
              f"예측 {ph:.0f}-{pa:.0f} / 실제 {g['home_final']}-{g['away_final']} "
              f"(평균 오차 {err:.1f}점){'  ✔ 최종 득점대 적중' if hit else ''}")
    if quiet:
        return sum(errors) / len(errors) if errors else None
    if errors:
        print(f"\n{len(errors)}경기 평균 오차: {sum(errors)/len(errors):.1f}점, "
              f"최종 득점대 둘 다 적중: {hits}경기")
    else:
        print("백테스트할 이번 시즌 경기가 아직 부족해요.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="games.csv")
    ap.add_argument("--home")
    ap.add_argument("--away")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--prior", default="last_season.csv")
    ap.add_argument("--h2h", default="h2h.csv")
    ap.add_argument("--total", type=float, help="언더오버 기준점 (예: 173.5)")
    ap.add_argument("--hcp", type=float, help="홈팀 핸디캡 (예: -3.5)")
    ap.add_argument("--absent", help='결장 선수 (예: "창원LG:아치 굿윈,원주DB:레이션 해먼즈")')
    ap.add_argument("--players", default="players.csv")
    ap.add_argument("--boost", help='팀 점수 수동 보정 (예: "원주DB:+3")')
    ap.add_argument("--season", help="이번 시즌 이름 바꾸기 (백테스트용, 예: 2025-26R6)")
    args = ap.parse_args()
    ARGS = args
    if args.season:
        CURRENT_SEASON = args.season

    PRIOR.update(load_prior(args.prior))
    H2H.update(load_h2h(args.h2h))
    PLAYERS.update(load_players(args.players))

    games = load_games(args.data)
    cur_games = games[games["season"] == CURRENT_SEASON]
    if len(PRIOR) and len(cur_games):
        cur_avg = (cur_games["home_final"].mean() + cur_games["away_final"].mean()) / 2
        last_avg = sum(p["pts"] for p in PRIOR.values()) / len(PRIOR)
        n = len(cur_games)
        LEAGUE.update(n=n, cur=cur_avg, last=last_avg,
                      adj=(cur_avg - last_avg) * n / (n + LEAGUE_K))
    if args.backtest:
        backtest(games)
    else:
        predict(team_rows(games), args.home, args.away)
