"""
백테스트 결과를 브라우저에서 경기별 카드로 보기

사용법:
    python report.py                       # games.csv 백테스트 → backtest_report.html 열기
    python report.py --data games_r6.csv --prior prior_r1-5.csv --season 2025-26R6
    python report.py --no-open             # 파일만 만들고 브라우저는 안 열기

경기마다 매치 4칸(전반 홈·원정, 최종 홈·원정 득점대), 전반·후반·최종 점수, 승패, 점수 차를
'예측 → 실제'로 보여줘요. 설정값 슬라이더를 움직이면 브라우저에서 바로 다시 계산해요.
결과 파일은 인터넷 없이도 열리는 HTML 한 개예요.
"""

import argparse
import json
import pathlib
import webbrowser
from datetime import datetime

import pandas as pd

import predict

PARAMS = ["HOME_ADV", "BLEND_K", "KEEP_PTS", "KEEP_OPP", "LEAGUE_K", "HALF_RATIO", "HALF_K"]


def build_html(games, season):
    """경기 원본·지난 시즌 평균·설정값을 HTML에 넣어요. 백테스트는 브라우저에서 다시 계산해요."""
    def num(v):
        return None if pd.isna(v) else int(v)

    payload = {
        "games": [{"date": str(g["date"].date()), "season": g["season"], "home": g["home"], "away": g["away"],
                   "home_half": num(g["home_half"]), "away_half": num(g["away_half"]),
                   "home_final": int(g["home_final"]), "away_final": int(g["away_final"])}
                  for _, g in games.iterrows()],
        "prior": predict.PRIOR,
        "current": season, "last": predict.LAST_SEASON,
        "half_bins": predict.HALF_BINS, "final_bins": predict.FINAL_BINS,
        "params": {k: getattr(predict, k) for k in PARAMS},
        # 최다 확률 조합 계산용 (predict.combo_probs와 같은 값)
        "sim": {"HALF_SD": predict.HALF_SD, "SECOND_SD": predict.SECOND_SD, "SECOND_CORR": predict.SECOND_CORR,
                "zs": predict._ZS.tolist(), "zw": predict._ZW.tolist()},
    }
    data = json.dumps(payload, ensure_ascii=False, default=float)
    created = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (TEMPLATE.replace("__DATA__", data)
                    .replace("__SEASON__", season)
                    .replace("__CREATED__", created))


TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KBL 백테스트 리포트</title>
<style>
:root {
  color-scheme: light;
  --bg: #f4f3f0; --surface: #fcfcfb; --surface-2: #f4f3f0; --border: #e3e2dd;
  --text: #0b0b0b; --text-2: #52514e; --muted: #8a8984; --grid: #ebeae6;
  --s1: #2a78d6; --s2: #eb6834;
  --good: #007a00; --good-bg: #e3f3e3; --good-bd: #b9e0b9;
  --bad: #c43c3b; --bad-bg: #fbe9e8; --bad-bd: #f1c4c2;
  --band: rgba(42,120,214,.08);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #111110; --surface: #1a1a19; --surface-2: #222220; --border: #2f2f2c;
    --text: #fff; --text-2: #c3c2b7; --muted: #8f8e86; --grid: #2a2a27;
    --s1: #3987e5; --s2: #d95926;
    --good: #5cc45c; --good-bg: #17291a; --good-bd: #24502a;
    --bad: #e66767; --bad-bg: #331b1b; --bad-bd: #5c2a2a;
    --band: rgba(57,135,229,.12);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --bg: #111110; --surface: #1a1a19; --surface-2: #222220; --border: #2f2f2c;
  --text: #fff; --text-2: #c3c2b7; --muted: #8f8e86; --grid: #2a2a27;
  --s1: #3987e5; --s2: #d95926;
  --good: #5cc45c; --good-bg: #17291a; --good-bd: #24502a;
  --bad: #e66767; --bad-bg: #331b1b; --bad-bd: #5c2a2a;
  --band: rgba(57,135,229,.12);
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 "Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", system-ui, sans-serif; }
.wrap { max-width: 980px; margin: 0 auto; padding: 28px 16px 60px; }
header { display: flex; justify-content: space-between; align-items: flex-end; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }
h1 { font-size: 22px; margin: 0; }
h2 { font-size: 15px; margin: 0 0 2px; }
.sub, .desc { color: var(--text-2); font-size: 12px; }
.desc { margin: 0 0 10px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.btn { background: var(--surface); color: var(--text-2); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 10px; cursor: pointer; font: inherit; font-size: 12px; }
.btn:hover { color: var(--text); }
.num { font-variant-numeric: tabular-nums; }
.ok { color: var(--good); } .no { color: var(--bad); }

/* 요약 */
.summary { display: grid; grid-template-columns: 1.4fr 1fr; gap: 12px; margin-bottom: 12px; }
@media (max-width: 720px) { .summary { grid-template-columns: 1fr; } }
.match4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 10px; }
.m4 { background: var(--surface-2); border-radius: 8px; padding: 8px; text-align: center; }
.m4 .l { font-size: 11px; color: var(--text-2); }
.m4 .v { font-size: 20px; font-weight: 700; }
.m4 .s { font-size: 11px; color: var(--muted); }
.allhit { margin-top: 10px; font-size: 13px; color: var(--text-2); }
.allhit b { color: var(--text); font-size: 16px; }
.kv { display: grid; grid-template-columns: 1fr auto; gap: 8px 12px; align-items: baseline; margin-top: 10px; }
.kv .l { color: var(--text-2); font-size: 13px; }
.kv .v { font-size: 18px; font-weight: 700; text-align: right; }
.delta { font-size: 12px; font-weight: 600; margin-left: 4px; }
.delta.better { color: var(--good); } .delta.worse { color: var(--bad); }

/* 설정·필터 */
details.panel { margin-bottom: 12px; }
details.panel > summary { cursor: pointer; font-weight: 600; font-size: 14px; list-style: none; display: flex; justify-content: space-between; align-items: center; }
details.panel > summary::-webkit-details-marker { display: none; }
details.panel > summary::after { content: '펼치기 ▾'; color: var(--muted); font-size: 12px; font-weight: 400; }
details.panel[open] > summary::after { content: '접기 ▴'; }
.sliders { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px 20px; margin: 14px 0 10px; }
.sl label { display: flex; justify-content: space-between; font-size: 13px; font-weight: 600; }
.sl label b { color: var(--s1); }
.sl label b.changed { color: var(--s2); }
.sl input { width: 100%; accent-color: var(--s1); }
.sl .hint { color: var(--muted); font-size: 11px; font-weight: 400; }
pre { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-size: 12px; overflow-x: auto; }
.filters { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 18px 0 10px; }
.filters h2 { margin-right: auto; }
select { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; font: inherit; font-size: 13px; }

/* 경기 카드 */
.games { display: grid; gap: 12px; }
.g-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.g-date { color: var(--text-2); font-size: 12px; min-width: 70px; }
.g-teams { font-size: 17px; font-weight: 700; margin-right: auto; }
.g-teams .vs { color: var(--muted); font-weight: 400; font-size: 13px; margin: 0 6px; }
.g-teams small { color: var(--muted); font-weight: 400; font-size: 11px; margin-left: 3px; }
.badge { font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 999px; border: 1px solid; }
.badge.ok { background: var(--good-bg); border-color: var(--good-bd); }
.badge.no { background: var(--surface-2); border-color: var(--border); color: var(--text-2); }
.badge.all { background: var(--good); border-color: var(--good); color: var(--surface); }

.picks { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
@media (max-width: 600px) { .picks { grid-template-columns: repeat(2, 1fr); } }
.pick { border: 1px solid var(--border); border-radius: 10px; padding: 8px 10px; background: var(--surface-2); }
.pick.ok { background: var(--good-bg); border-color: var(--good-bd); }
.pick.no { background: var(--bad-bg); border-color: var(--bad-bd); }
.pick .t { font-size: 11px; color: var(--text-2); display: flex; justify-content: space-between; }
.pick .t b { font-size: 13px; }
.pick .p { font-size: 17px; font-weight: 700; margin: 2px 0; }
.pick .a { font-size: 12px; color: var(--text-2); }
.combo { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 8px; font-size: 12px; }
.combo .l { color: var(--text-2); margin-right: 2px; }
.chip { padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface-2); }
.chip.ok { background: var(--good-bg); border-color: var(--good-bd); color: var(--good); font-weight: 700; }
.chip.no { background: var(--bad-bg); border-color: var(--bad-bd); }
.cmp { width: 100%; border-collapse: collapse; margin: 12px 0 4px; font-size: 12px; }
.cmp th, .cmp td { padding: 4px 6px; text-align: center; border-bottom: 1px solid var(--border); }
.cmp th { color: var(--text-2); font-weight: 600; }
.cmp td:first-child, .cmp th:first-child { text-align: left; color: var(--text-2); }

.scores { width: 100%; border-collapse: collapse; margin-top: 12px; font-variant-numeric: tabular-nums; }
.scores th, .scores td { padding: 6px 8px; text-align: center; border-bottom: 1px solid var(--border); }
.scores th { font-size: 12px; color: var(--text-2); font-weight: 600; }
.scores td:first-child, .scores th:first-child { text-align: left; color: var(--text-2); font-size: 12px; width: 52px; }
.scores tr.act td:not(:first-child) { font-weight: 700; font-size: 15px; }
.scores tr.pred td:not(:first-child) { color: var(--text-2); }
.scores .colon { color: var(--muted); margin: 0 4px; }
.scores .na { color: var(--muted); font-size: 12px; }

.outcome { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
@media (max-width: 600px) { .outcome { grid-template-columns: 1fr; } }
.oc { background: var(--surface-2); border-radius: 8px; padding: 8px 10px; font-size: 13px; }
.oc .l { font-size: 11px; color: var(--text-2); display: flex; justify-content: space-between; }
.oc .arrow { color: var(--muted); margin: 0 4px; }

/* 그래프 */
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 16px; margin-top: 14px; }
.charts .card { background: var(--surface-2); border: none; }
.legend { display: flex; gap: 14px; font-size: 12px; color: var(--text-2); margin-bottom: 6px; flex-wrap: wrap; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: -1px; }
svg { width: 100%; height: auto; display: block; overflow: visible; }
svg text { fill: var(--muted); font-size: 11px; }
#tip { position: fixed; pointer-events: none; background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-size: 12px;
  box-shadow: 0 4px 16px rgba(0,0,0,.15); opacity: 0; transition: opacity .1s; z-index: 10; }
.empty { padding: 40px; text-align: center; color: var(--text-2); }
footer { color: var(--muted); font-size: 12px; margin-top: 16px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>KBL 백테스트</h1>
      <div class="sub">시즌 __SEASON__ · 각 경기를 그 경기 전 데이터만으로 예측해서 실제와 비교 · 생성 __CREATED__</div>
    </div>
    <button class="btn" id="themeBtn">다크/라이트</button>
  </header>

  <div id="summary"></div>

  <details class="panel card">
    <summary>설정값 바꿔보기</summary>
    <p class="desc" style="margin-top:6px">슬라이더를 움직이면 아래 모든 경기를 바로 다시 예측해요. 괄호 속 회색 숫자는 predict.py 현재 값이에요.</p>
    <div class="sliders" id="sliders"></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start">
      <button class="btn" id="resetBtn">predict.py 값으로 되돌리기</button>
      <details style="flex:1;min-width:220px"><summary class="desc" style="cursor:pointer">이 설정을 predict.py에 쓰려면</summary><pre id="snippet"></pre></details>
    </div>
  </details>

  <details class="panel card" id="chartPanel">
    <summary>그래프로 보기</summary>
    <div class="charts">
      <div class="card"><h2>경기별 최종 점수 오차</h2><p class="desc">막대가 낮을수록 잘 맞춘 경기 (팀당 평균)</p><div id="c1"></div></div>
      <div class="card"><h2>예측 vs 실제 최종 점수</h2><p class="desc">대각선에 가까울수록 정확 · 음영은 ±10점</p>
        <div class="legend"><span><i style="background:var(--s1)"></i>홈팀</span><span><i style="background:var(--s2)"></i>원정팀</span></div><div id="c2"></div></div>
    </div>
  </details>

  <div class="filters">
    <h2>경기별 결과</h2>
    <select id="teamSel"><option value="">모든 팀</option></select>
    <select id="sortSel"><option value="new">최신 경기부터</option><option value="old">오래된 경기부터</option><option value="best">많이 맞힌 순</option></select>
  </div>
  <div class="games" id="games"></div>

  <footer>매치 칸 = 득점대(구간)를 맞혔는지 · 예측 점수는 반올림해서 보여줘요 (칸 판정도 반올림 기준) ·
    상대전적·결장·수동 보정은 백테스트에 들어가지 않아요 (predict.py --backtest와 같음) · 전반 기록이 없는 경기는 전반 칸을 세지 않아요 ·
    최다 확률 조합은 전반 기록이 있는 경기만 4칸으로 세요</footer>
</div>
<div id="tip"></div>

<script>
const INPUT = __DATA__;
const SLIDERS = [
  ['HOME_ADV', '홈 이점', 0, 6, 0.5, '홈팀 +N점, 원정팀 −N점'],
  ['BLEND_K', '이번 시즌 믿는 속도', 1, 30, 1, '이 경기 수가 쌓이면 지난 시즌과 반반'],
  ['KEEP_PTS', '지난 시즌 득점 유지율', 0, 1, 0.05, '0이면 득점은 리그 평균으로'],
  ['KEEP_OPP', '지난 시즌 실점 유지율', 0, 1, 0.05, '0이면 실점은 리그 평균으로'],
  ['LEAGUE_K', '리그 득점 변화 믿는 속도', 1, 30, 1, '작을수록 이번 시즌 득점 수준을 빨리 반영'],
  ['HALF_RATIO', '시즌 초 전반 비율', 0.4, 0.56, 0.01, '전반 기록이 쌓이면 리그 실측 비율로 옮겨감'],
  ['HALF_K', '팀 전반 비율 믿는 속도', 1, 60, 1, '팀 경기가 이만큼 쌓이면 리그 비율과 반반'],
];
const BASE = { ...INPUT.params };
let P = { ...BASE };
let DATA = [], BASE_STATS = null;
const $ = id => document.getElementById(id);
const tip = $('tip');
const NS = 'http://www.w3.org/2000/svg';
const f1 = v => v.toFixed(1);
const r0 = v => pyRound(v);
const sgn = v => (v > 0 ? '+' : '') + v;
const DAYS = '일월화수목금토';

$('themeBtn').onclick = () => {
  const cur = document.documentElement.dataset.theme
    || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.dataset.theme = cur === 'dark' ? 'light' : 'dark';
};

/* ── 백테스트 계산 (predict.py와 같은 방식) ── */
function pyRound(x) {  // 파이썬 round()와 같게 (0.5는 짝수 쪽으로)
  const f = Math.floor(x), d = x - f;
  if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1;
  return Math.round(x);
}
function toBin(v, bins) {
  const s = pyRound(v);
  for (const [lo, hi, name] of bins) if (lo <= s && s <= hi) return name;
  return '?';
}
const avg = a => a.reduce((s, v) => s + v, 0) / a.length;

function leagueHalfRatio(past, p) {  // predict.py league_half_ratio와 같음
  let half = 0, pts = 0, m = 0;
  past.filter(g => g.season === INPUT.current).forEach(g => {
    if (g.home_half != null) { half += g.home_half; pts += g.home_final; m++; }
    if (g.away_half != null) { half += g.away_half; pts += g.away_final; m++; }
  });
  if (!m) return p.HALF_RATIO;
  const w = (m / 2) / (m / 2 + p.LEAGUE_K);
  return (1 - w) * p.HALF_RATIO + w * half / pts;
}

function profile(past, team, p) {
  const rows = [];
  past.forEach(g => {
    if (g.home === team) rows.push({ season: g.season, pts: g.home_final, opp: g.away_final, half: g.home_half });
    if (g.away === team) rows.push({ season: g.season, pts: g.away_final, opp: g.home_final, half: g.away_half });
  });
  const last = rows.filter(r => r.season === INPUT.last), cur = rows.filter(r => r.season === INPUT.current);
  let lastAvg = null;
  const pr = INPUT.prior, teams = Object.keys(pr);
  if (last.length) lastAvg = { pts: avg(last.map(r => r.pts)), opp: avg(last.map(r => r.opp)) };
  else if (pr[team]) {
    const mp = avg(teams.map(t => pr[t].pts)), mo = avg(teams.map(t => pr[t].opp_pts));
    lastAvg = { pts: mp + p.KEEP_PTS * (pr[team].pts - mp), opp: mo + p.KEEP_OPP * (pr[team].opp_pts - mo) };
  }
  const n = cur.length;
  if (!lastAvg && !n) return null;
  const w = n / (n + p.BLEND_K);
  const blend = k => !lastAvg ? avg(cur.map(r => r[k])) : !n ? lastAvg[k] : (1 - w) * lastAvg[k] + w * avg(cur.map(r => r[k]));
  const hv = rows.filter(r => r.half != null);
  const lg = leagueHalfRatio(past, p), wh = hv.length / (hv.length + p.HALF_K);  // predict.py team_profile과 같음
  const ratio = hv.length ? (1 - wh) * lg + wh * hv.reduce((s, r) => s + r.half, 0) / hv.reduce((s, r) => s + r.pts, 0) : lg;
  return { pts: blend('pts'), opp: blend('opp'), ratio };
}

/* ── 최다 확률 조합 (predict.py combo_probs와 같은 계산) ── */
function ncdf(x) {
  x /= Math.SQRT2;
  const a = Math.abs(x), t = 1 / (1 + 0.3275911 * a);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-a * a);
  return 0.5 * (1 + Math.sign(x) * y);
}
function comboSide(muH, muS) {  // [공통오차][전반칸][최종칸] 확률
  const S = INPUT.sim, hb = INPUT.half_bins, fb = INPUT.final_bins, nh = hb.length, nf = fb.length;
  const r = S.SECOND_CORR, own = S.SECOND_SD * Math.sqrt(1 - r), com = S.SECOND_SD * Math.sqrt(r);
  const fe = [-Infinity, ...fb.slice(0, -1).map(b => b[1] + 0.5), Infinity];
  const zs = S.zs, sd = S.HALF_SD, nz = zs.length, cell = nh * nf;
  const out = new Float64Array(nz * cell);  // [공통오차][전반칸][최종칸]
  for (let h = Math.floor(muH - 6 * sd); h <= Math.ceil(muH + 6 * sd); h++) {
    const ph = ncdf((h + 0.5 - muH) / sd) - ncdf((h - 0.5 - muH) / sd);
    let b = 0; while (b < nh - 1 && h > hb[b][1] + 0.5) b++;
    for (let zi = 0; zi < nz; zi++) {
      const m = h + muS + com * zs[zi], base = zi * cell + b * nf;
      let prev = 0;
      for (let f = 0; f < nf; f++) {
        const c = f === nf - 1 ? 1 : ncdf((fe[f + 1] - m) / own);
        out[base + f] += ph * (c - prev); prev = c;
      }
    }
  }
  return out;
}
function topCombo(p) {  // 4칸 조합 중 모델 확률 최대
  const nh = INPUT.half_bins.length, nf = INPUT.final_bins.length, w = INPUT.sim.zw, nz = w.length, cell = nh * nf;
  const A = comboSide(p.hh, p.hf - p.hh), B = comboSide(p.ah, p.af - p.ah);
  let best = -1, bi = null;
  for (let a = 0; a < nh; a++) for (let b = 0; b < nh; b++) for (let c = 0; c < nf; c++) for (let d = 0; d < nf; d++) {
    let s = 0;
    for (let z = 0; z < nz; z++) s += w[z] * A[z * cell + a * nf + c] * B[z * cell + b * nf + d];
    if (s > best + 1e-12) { best = s; bi = [a, b, c, d]; }
  }
  const bins = [INPUT.half_bins, INPUT.half_bins, INPUT.final_bins, INPUT.final_bins];
  return { names: bi.map((k, i) => bins[i][k][2]), prob: best };
}

function band5(m) {  // 승5패 구간 (홈 기준 점수 차)
  return m >= 6 ? 'home' : m <= -6 ? 'away' : 'close';
}

function runBacktest(p) {
  const games = INPUT.games.map((g, i) => ({ ...g, i })).sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : a.i - b.i);
  const teams = Object.keys(INPUT.prior);
  const out = [];
  games.filter(g => g.season === INPUT.current).forEach(g => {
    const past = games.filter(x => x.date < g.date);  // 그 경기 전 데이터만
    const h = profile(past, g.home, p), a = profile(past, g.away, p);
    if (!h || !a) return;
    let ph = (h.pts + a.opp) / 2 + p.HOME_ADV, pa = (a.pts + h.opp) / 2 - p.HOME_ADV;
    const prev = past.filter(x => x.season === INPUT.current);
    if (teams.length && prev.length) {
      const curAvg = (avg(prev.map(x => x.home_final)) + avg(prev.map(x => x.away_final))) / 2;
      const lastAvg = avg(teams.map(t => INPUT.prior[t].pts));
      const adj = (curAvg - lastAvg) * prev.length / (prev.length + p.LEAGUE_K);
      ph += adj; pa += adj;
    }
    const pred = { hh: ph * h.ratio, ah: pa * a.ratio, hf: ph, af: pa };
    const act = { hh: g.home_half, ah: g.away_half, hf: g.home_final, af: g.away_final };
    const hasHalf = act.hh != null && act.ah != null;
    const pick = (k, bins) => {
      const pb = toBin(pred[k], bins);
      if (act[k] == null) return { pred: pb, act: null, hit: null };
      const ab = toBin(act[k], bins);
      return { pred: pb, act: ab, hit: pb === ab };
    };
    const picks = [
      { label: '전반', side: 'home', ...pick('hh', INPUT.half_bins) },
      { label: '전반', side: 'away', ...pick('ah', INPUT.half_bins) },
      { label: '최종', side: 'home', ...pick('hf', INPUT.final_bins) },
      { label: '최종', side: 'away', ...pick('af', INPUT.final_bins) },
    ];
    const tc = topCombo(pred);
    const combo = { prob: tc.prob, picks: tc.names.map((name, i) => ({ pred: name, hit: picks[i].hit == null ? null : name === picks[i].act })) };
    combo.hits = combo.picks.filter(x => x.hit).length;
    const pm = r0(ph) - r0(pa), am = act.hf - act.af;
    out.push({
      date: g.date, home: g.home, away: g.away, pred, act, hasHalf, picks, combo,
      hits: picks.filter(x => x.hit).length, counted: picks.filter(x => x.hit != null).length,
      err: (Math.abs(ph - act.hf) + Math.abs(pa - act.af)) / 2,
      pm: ph - pa, am, winner_hit: (ph > pa) === (am > 0),
      band_hit: band5(pm) === band5(am),
    });
  });
  return out;
}

function stats(d) {
  const n = d.length || 1;
  const slot = i => { const c = d.filter(x => x.picks[i].hit != null); return { hit: c.filter(x => x.picks[i].hit).length, n: c.length }; };
  const cslot = i => d.filter(x => x.combo.picks[i].hit).length;
  const full = d.filter(x => x.counted === 4);
  return {
    n: d.length, slots: [0, 1, 2, 3].map(slot),
    all4: d.filter(x => x.counted === 4 && x.hits === 4).length,
    cslots: [0, 1, 2, 3].map(cslot), call4: full.filter(x => x.combo.hits === 4).length,
    cexp: full.reduce((s, x) => s + x.combo.prob, 0), n4: full.length,
    final2: d.filter(x => x.picks[2].hit && x.picks[3].hit).length,
    win: d.filter(x => x.winner_hit).length, band: d.filter(x => x.band_hit).length,
    err: d.reduce((s, x) => s + x.err, 0) / n,
  };
}
function delta(cur, base, lowerBetter, fmt = v => v) {
  const d = cur - base;
  if (Math.abs(d) < 0.05) return '';
  const better = lowerBetter ? d < 0 : d > 0;
  return `<span class="delta ${better ? 'better' : 'worse'}">${d > 0 ? '+' : ''}${fmt(d)}</span>`;
}
const pct = (a, b) => b ? Math.round(a / b * 100) + '%' : '—';

/* ── 요약 ── */
function renderSummary() {
  const s = stats(DATA), b = BASE_STATS;
  const names = ['전반 홈', '전반 원정', '최종 홈', '최종 원정'];
  $('summary').innerHTML = `
  <div class="summary">
    <div class="card">
      <h2>매치 4칸 적중률</h2>
      <div class="desc">${s.n}경기 · 칸마다 득점대를 맞힌 비율</div>
      <div class="match4">${s.slots.map((x, i) => `
        <div class="m4"><div class="l">${names[i]}</div>
        <div class="v num">${pct(x.hit, x.n)}${delta(x.hit, b.slots[i].hit, false)}</div>
        <div class="s">${x.n ? `${x.hit} / ${x.n}경기` : '전반 기록 없음'}</div></div>`).join('')}
      </div>
      <div class="allhit">4칸 모두 적중 <b class="num">${s.all4}경기</b>${delta(s.all4, b.all4, false)}
        · 최종 2칸 적중 <b class="num">${s.final2}경기</b>${delta(s.final2, b.final2, false)}</div>
      <table class="cmp num">
        <tr><th>고르는 방법</th>${names.map(x => `<th>${x}</th>`).join('')}<th>4칸</th></tr>
        <tr><td>예상 점수 득점대</td>${s.slots.map(x => `<td>${x.hit}</td>`).join('')}<td><b>${s.all4}</b></td></tr>
        <tr><td>최다 확률 조합</td>${s.cslots.map(x => `<td>${x}</td>`).join('')}<td><b>${s.call4}</b>${delta(s.call4, b.call4, false)}</td></tr>
      </table>
      <div class="desc">최다 확률 조합 = 모델이 4칸을 한 번에 맞힐 확률이 가장 높다고 본 조합 (predict.py "전반+최종" 1위).
        모델 기대 4칸 적중 ${f1(s.cexp)}경기 / ${s.n4}경기</div>
    </div>
    <div class="card">
      <h2>다른 게임으로 보면</h2>
      <div class="kv">
        <span class="l">승패 적중</span><span class="v num">${pct(s.win, s.n)} <span class="desc">${s.win}/${s.n}</span>${delta(s.win, b.win, false)}</span>
        <span class="l">승5패 적중 <span class="desc">(6점차+ / 5점 이내)</span></span><span class="v num">${pct(s.band, s.n)} <span class="desc">${s.band}/${s.n}</span>${delta(s.band, b.band, false)}</span>
        <span class="l">최종 점수 평균 오차 <span class="desc">(팀당)</span></span><span class="v num">${f1(s.err)}점${delta(s.err, b.err, true, f1)}</span>
      </div>
    </div>
  </div>`;
}

/* ── 경기 카드 ── */
function sideName(d, side) { return side === 'home' ? d.home : d.away; }
function marginText(d, m) {  // 예: '창원LG 2점 차 승 (5점 이내)'
  if (m === 0) return '동점 (5점 이내)';
  return `${m > 0 ? d.home : d.away} ${Math.abs(m)}점 차 승 (${Math.abs(m) >= 6 ? '6점차+' : '5점 이내'})`;
}
function winnerText(d, m) { return `${m > 0 ? d.home : d.away} 승`; }
function mark(hit) { return hit ? '<b class="ok">✓ 적중</b>' : '<b class="no">✗</b>'; }

function card(d) {
  const dt = new Date(d.date + 'T00:00:00');
  const badge = d.counted === 4 && d.hits === 4
    ? '<span class="badge all">4칸 모두 적중!</span>'
    : `<span class="badge ${d.hits ? 'ok' : 'no'}">매치 ${d.hits}/${d.counted}칸 적중</span>`;
  const picks = d.picks.map(x => {
    const cls = x.hit == null ? '' : x.hit ? 'ok' : 'no';
    const actScore = d.act[(x.side === 'home' ? 'h' : 'a') + (x.label === '전반' ? 'h' : 'f')];
    const predScore = d.pred[(x.side === 'home' ? 'h' : 'a') + (x.label === '전반' ? 'h' : 'f')];
    return `<div class="pick ${cls}" title="예측 ${f1(predScore)}점">
      <div class="t"><span>${x.label} · ${sideName(d, x.side)}</span>${x.hit == null ? '' : x.hit ? '<b class="ok">✓</b>' : '<b class="no">✗</b>'}</div>
      <div class="p">${x.pred}</div>
      <div class="a">${x.hit == null ? '실제 전반 기록 없음' : `실제 <b class="num">${actScore}</b>점${x.hit ? '' : ` → ${x.act}`}`}</div>
    </div>`;
  }).join('');
  const PR = d.pred, A = d.act;
  const sc = (h, a) => `<span class="num">${h}</span><span class="colon">:</span><span class="num">${a}</span>`;
  const predHalf = sc(r0(PR.hh), r0(PR.ah));
  const predSecond = sc(r0(PR.hf) - r0(PR.hh), r0(PR.af) - r0(PR.ah));
  const actHalf = d.hasHalf ? sc(A.hh, A.ah) : '<span class="na">기록 없음</span>';
  const actSecond = d.hasHalf ? sc(A.hf - A.hh, A.af - A.ah) : '<span class="na">기록 없음</span>';
  const pmR = r0(PR.hf) - r0(PR.af);
  return `<div class="card">
    <div class="g-head">
      <span class="g-date num">${d.date.slice(5).replace('-', '.')} (${DAYS[dt.getDay()]})</span>
      <span class="g-teams">${d.home}<small>홈</small><span class="vs">vs</span>${d.away}<small>원정</small></span>
      ${badge}
    </div>
    <div class="picks">${picks}</div>
    <div class="combo"><span class="l">최다 확률 조합 <span class="num">(모델 ${(d.combo.prob * 100).toFixed(1)}%)</span></span>
      ${d.combo.picks.map(x => `<span class="chip ${x.hit == null ? '' : x.hit ? 'ok' : 'no'}">${x.pred}</span>`).join('')}
      <b class="num">${d.combo.hits}/${d.counted}칸</b></div>
    <table class="scores">
      <tr><th></th><th>전반</th><th>후반</th><th>최종</th></tr>
      <tr class="pred"><td>예측</td><td>${predHalf}</td><td>${predSecond}</td><td>${sc(r0(PR.hf), r0(PR.af))}</td></tr>
      <tr class="act"><td>실제</td><td>${actHalf}</td><td>${actSecond}</td><td>${sc(A.hf, A.af)}</td></tr>
    </table>
    <div class="outcome">
      <div class="oc"><div class="l"><span>승패</span>${mark(d.winner_hit)}</div>
        ${winnerText(d, d.pm)}<span class="arrow">→</span><b>${winnerText(d, d.am)}</b></div>
      <div class="oc"><div class="l"><span>점수 차 · 승5패</span>${mark(d.band_hit)}</div>
        ${marginText(d, pmR)}<span class="arrow">→</span><b>${marginText(d, d.am)}</b></div>
    </div>
  </div>`;
}

function renderGames() {
  const team = $('teamSel').value, sort = $('sortSel').value;
  let rows = DATA.filter(d => !team || d.home === team || d.away === team);
  rows = [...rows];
  if (sort === 'new') rows.reverse();
  if (sort === 'best') rows.sort((a, b) => b.hits - a.hits || a.err - b.err);
  $('games').innerHTML = rows.length ? rows.map(card).join('') : '<div class="card empty">해당 팀 경기가 없어요.</div>';
}

/* ── 설정 슬라이더 ── */
function buildControls() {
  $('sliders').innerHTML = SLIDERS.map(([k, label, min, max, step, hint]) => `
    <div class="sl"><label>${label} <span><b id="v_${k}" class="num"></b> <span class="hint">(${BASE[k]})</span></span></label>
    <input type="range" id="s_${k}" min="${min}" max="${max}" step="${step}" value="${BASE[k]}">
    <div class="hint">${k} · ${hint}</div></div>`).join('');
  SLIDERS.forEach(([k]) => $('s_' + k).oninput = e => { P[k] = +e.target.value; update(); });
  $('resetBtn').onclick = () => { P = { ...BASE }; SLIDERS.forEach(([k]) => $('s_' + k).value = BASE[k]); update(); };
  const teams = [...new Set(INPUT.games.filter(g => g.season === INPUT.current).flatMap(g => [g.home, g.away]))].sort();
  $('teamSel').innerHTML += teams.map(t => `<option>${t}</option>`).join('');
  $('teamSel').onchange = $('sortSel').onchange = renderGames;
  $('chartPanel').ontoggle = () => { if ($('chartPanel').open) renderCharts(); };
}
function update() {
  SLIDERS.forEach(([k]) => { const b = $('v_' + k); b.textContent = P[k]; b.className = 'num' + (P[k] !== BASE[k] ? ' changed' : ''); });
  $('snippet').textContent = SLIDERS.map(([k]) => `${k.padEnd(10)} = ${P[k]}`).join('\n');
  DATA = runBacktest(P);
  hideTip();
  if (!DATA.length) {
    $('summary').innerHTML = '<div class="card empty">백테스트할 이번 시즌 경기가 아직 부족해요.</div>';
    $('games').innerHTML = '';
    return;
  }
  renderSummary();
  renderGames();
  if ($('chartPanel').open) renderCharts();
}

/* ── 그래프 ── */
function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
function showTip(ev, html) {
  tip.innerHTML = html; tip.style.opacity = 1;
  const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + 'px'; tip.style.top = (ev.clientY + 14) + 'px';
}
function hideTip() { tip.style.opacity = 0; }
function ticks(lo, hi, step) { const o = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) o.push(v); return o; }
function renderCharts() {
  $('c1').innerHTML = ''; $('c2').innerHTML = '';
  if (!DATA.length) return;
  errorBars($('c1')); scatter($('c2'));
}
function errorBars(box) {
  const mean = avg(DATA.map(d => d.err));
  const W = 460, H = 240, m = { l: 34, r: 52, t: 10, b: 34 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}` }, box);
  const max = Math.max(20, Math.ceil(Math.max(...DATA.map(d => d.err)) / 5) * 5);
  const y = v => m.t + ih - v / max * ih;
  ticks(0, max, 5).forEach(v => {
    el('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: 'var(--grid)' }, svg);
    el('text', { x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, svg).textContent = v;
  });
  const bw = iw / DATA.length, barW = Math.min(28, bw * 0.6);
  DATA.forEach((d, i) => {
    const cx = m.l + bw * i + bw / 2, top = y(d.err), r = Math.min(4, barW / 2, y(0) - top);
    el('path', { d: `M${cx - barW / 2},${y(0)} V${top + r} Q${cx - barW / 2},${top} ${cx - barW / 2 + r},${top} H${cx + barW / 2 - r} Q${cx + barW / 2},${top} ${cx + barW / 2},${top + r} V${y(0)} Z`,
      fill: d.err <= mean ? 'var(--s1)' : 'var(--s2)' }, svg);
    el('text', { x: cx, y: H - m.b + 16, 'text-anchor': 'middle' }, svg).textContent = d.date.slice(5).replace('-', '.');
    const hit = el('rect', { x: m.l + bw * i, y: m.t, width: bw, height: ih, fill: 'transparent' }, svg);
    hit.onmousemove = e => showTip(e, `<b>${d.home} vs ${d.away}</b><br>예측 ${r0(d.pred.hf)} : ${r0(d.pred.af)}<br>실제 ${d.act.hf} : ${d.act.af}<br>팀당 오차 <b>${f1(d.err)}점</b>`);
    hit.onmouseleave = hideTip;
  });
  el('line', { x1: m.l, x2: W - m.r, y1: y(mean), y2: y(mean), stroke: 'var(--muted)', 'stroke-width': 1.5, 'stroke-dasharray': '4 4' }, svg);
  el('text', { x: W - m.r + 6, y: y(mean) + 4 }, svg).textContent = `평균 ${f1(mean)}`;
  el('text', { x: m.l + iw / 2, y: H - 2, 'text-anchor': 'middle' }, svg).textContent = '파랑 = 평균보다 잘 맞춤, 주황 = 못 맞춤';
}
function scatter(box) {
  const W = 460, H = 290, m = { l: 38, r: 12, t: 10, b: 36 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = el('svg', { viewBox: `0 0 ${W} ${H}` }, box);
  const vals = DATA.flatMap(d => [d.pred.hf, d.pred.af, d.act.hf, d.act.af]);
  const lo = Math.floor((Math.min(...vals) - 5) / 10) * 10, hi = Math.ceil((Math.max(...vals) + 5) / 10) * 10;
  const x = v => m.l + (v - lo) / (hi - lo) * iw, y = v => m.t + ih - (v - lo) / (hi - lo) * ih;
  ticks(lo, hi, 10).forEach(v => {
    el('line', { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: 'var(--grid)' }, svg);
    el('text', { x: m.l - 6, y: y(v) + 4, 'text-anchor': 'end' }, svg).textContent = v;
    el('text', { x: x(v), y: H - m.b + 16, 'text-anchor': 'middle' }, svg).textContent = v;
  });
  el('polygon', { points: `${x(lo)},${y(lo + 10)} ${x(hi - 10)},${y(hi)} ${x(hi)},${y(hi)} ${x(hi)},${y(hi - 10)} ${x(lo + 10)},${y(lo)} ${x(lo)},${y(lo)}`, fill: 'var(--band)' }, svg);
  el('line', { x1: x(lo), y1: y(lo), x2: x(hi), y2: y(hi), stroke: 'var(--muted)', 'stroke-dasharray': '4 4' }, svg);
  el('text', { x: m.l + iw / 2, y: H - 2, 'text-anchor': 'middle' }, svg).textContent = '예측 점수';
  el('text', { x: 10, y: m.t + ih / 2, 'text-anchor': 'middle', transform: `rotate(-90 10 ${m.t + ih / 2})` }, svg).textContent = '실제 점수';
  DATA.forEach(d => [['hf', d.home, 'var(--s1)', '홈'], ['af', d.away, 'var(--s2)', '원정']].forEach(([k, name, c, lab]) => {
    const p = d.pred[k], a = d.act[k];
    const dot = el('circle', { cx: x(p), cy: y(a), r: 5, fill: c, stroke: 'var(--surface-2)', 'stroke-width': 2 }, svg);
    const hit = el('circle', { cx: x(p), cy: y(a), r: 12, fill: 'transparent' }, svg);
    hit.onmousemove = e => { dot.setAttribute('r', 7); showTip(e, `<b>${name}</b> (${lab}) · ${d.date.slice(5)}<br>예측 ${r0(p)} → 실제 ${a}`); };
    hit.onmouseleave = () => { dot.setAttribute('r', 5); hideTip(); };
  }));
}

BASE_STATS = stats(runBacktest(BASE));
buildControls();
update();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="games.csv")
    ap.add_argument("--prior", default="last_season.csv")
    ap.add_argument("--season", help="백테스트할 시즌 이름 (예: 2025-26R6)")
    ap.add_argument("--out", default="backtest_report.html")
    ap.add_argument("--no-open", action="store_true", help="브라우저 자동으로 열지 않기")
    args = ap.parse_args()

    if args.season:
        predict.CURRENT_SEASON = args.season
        predict.LAST_SEASON = predict.prev_season(args.season, predict.LAST_SEASON)
    predict.PRIOR.update(predict.load_prior(args.prior))
    games = predict.load_games(args.data)
    recs = predict.backtest_records(games)

    out = pathlib.Path(args.out).resolve()
    out.write_text(build_html(games, predict.CURRENT_SEASON), encoding="utf-8")
    print(f"리포트 저장: {out}  ({len(recs)}경기)")
    if not args.no_open:
        webbrowser.open(out.as_uri())
