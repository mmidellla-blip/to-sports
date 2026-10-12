"""
KBO 백테스트 결과를 브라우저에서 보기

사용법:
    python report_kbo.py                  # 최근 시즌 → backtest_kbo.html 열기
    python report_kbo.py --season 2025
    python report_kbo.py --no-open        # 파일만 만들기

경기 전날까지 데이터만으로 예측한 결과를 실제와 비교해요.
시즌 요약, 득점대별 '예측 확률 vs 실제 비율', 팀별 오차, 월별 추이, 경기별 상세를 보여줘요.
결과 파일은 인터넷 없이도 열리는 HTML 한 개예요.
"""
import argparse
import json
import math
import pathlib
import webbrowser
from collections import defaultdict

import predict_kbo as P


def records(games, season):
    gs = sorted([g for g in games if g["season"] == season], key=lambda g: g["date"])
    by_date = defaultdict(list)
    for g in gs:
        by_date[g["date"]].append(g)
    out = []
    for day in sorted(by_date):
        st = P.State(games, season, before=day)
        base = P.bin_probs(st.lg)
        for g in by_date[day]:
            p = P.predict(st, g["home"], g["away"], g["home_sp"], g["away_sp"], g["stadium"])
            out.append({
                "date": g["date"], "stadium": g["stadium"], "home": g["home"], "away": g["away"],
                "home_sp": g["home_sp"], "away_sp": g["away_sp"],
                "home_sp_n": round(p["home_sp_n"], 1), "away_sp_n": round(p["away_sp_n"], 1),
                "mu_home": round(p["mu_home"], 2), "mu_away": round(p["mu_away"], 2),
                "home_final": g["home_final"], "away_final": g["away_final"],
                "home_bins": [round(x, 4) for x in p["home_bins"]],
                "away_bins": [round(x, 4) for x in p["away_bins"]],
                "base": [round(x, 4) for x in base],
            })
    return out


def build_html(recs, season):
    payload = {"season": season, "bins": [b[2] for b in P.BINS], "games": recs,
               "params": {k: getattr(P, k) for k in ("TEAM_K", "KEEP_LAST", "SP_K", "PARK_K", "HOME_ADV", "DISPERSION")}}
    return TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False)).replace("__SEASON__", str(season))


TEMPLATE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KBO 백테스트 __SEASON__</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1b;--mute:#6b6b66;--line:#e4e3de;--acc:#2f6fdb;--acc2:#e08a2c;--good:#1f8a5b;--bad:#c94a3b;--chip:#eef2fb}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#151515;--card:#1f1f1e;--fg:#ecebe6;--mute:#9a9992;--line:#33332f;--acc:#6c9cf0;--acc2:#f0a957;--good:#4cc28c;--bad:#ef7a6a;--chip:#25304a}}
:root[data-theme=dark]{--bg:#151515;--card:#1f1f1e;--fg:#ecebe6;--mute:#9a9992;--line:#33332f;--acc:#6c9cf0;--acc2:#f0a957;--good:#4cc28c;--bad:#ef7a6a;--chip:#25304a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 -apple-system,"Segoe UI","Malgun Gothic",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0 0 12px}.sub{color:var(--mute);margin:0 0 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.tile .k{color:var(--mute);font-size:12px}.tile .v{font-size:24px;font-weight:700;margin-top:2px}.tile .n{color:var(--mute);font-size:12px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:760px){.grid2{grid-template-columns:1fr}}
svg text{fill:var(--mute);font-size:11px}
.legend{display:flex;gap:14px;color:var(--mute);font-size:12px;margin-top:6px}.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{color:var(--mute);font-weight:600;position:sticky;top:0;background:var(--card)}td.l,th.l{text-align:left}
.scroll{overflow:auto;max-height:560px}
.hit{color:var(--good);font-weight:700}.miss{color:var(--mute)}
.bar{display:inline-flex;gap:1px;vertical-align:middle}.bar i{display:inline-block;width:9px;background:var(--acc);border-radius:1px}
.bar i.act{background:var(--acc2)}
.controls{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}select,input{background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:6px 8px;font:inherit}
.note{color:var(--mute);font-size:12px;margin-top:8px}
</style></head><body><main>
<h1>KBO 득점 예측 백테스트 · <span id="season"></span> 시즌</h1>
<p class="sub">경기 전날까지의 데이터만으로 예측해서 실제 결과와 비교했어요. 득점대: 0~1 · 2~3 · 4~5 · 6~7 · 8~9 · 10+</p>
<div class="tiles" id="tiles"></div>
<div class="grid2">
 <div class="card"><h2>득점대별 · 예측 평균 확률 vs 실제 비율</h2><div id="calib"></div>
  <div class="legend"><span><i class="sw" style="background:var(--acc)"></i>모델 예측</span><span><i class="sw" style="background:var(--acc2)"></i>실제</span></div>
  <p class="note">두 막대 높이가 비슷할수록 확률이 믿을 만해요.</p></div>
 <div class="card"><h2>월별 · 평균 오차와 득점대 적중률</h2><div id="monthly"></div>
  <div class="legend"><span><i class="sw" style="background:var(--acc)"></i>평균 오차(점)</span><span><i class="sw" style="background:var(--acc2)"></i>최다확률 득점대 적중률</span></div></div>
</div>
<div class="card"><h2>팀별 결과</h2><div class="scroll" style="max-height:none"><table id="teams"></table></div></div>
<div class="card"><h2>경기별 상세</h2>
 <div class="controls"><select id="fTeam"><option value="">전체 팀</option></select><select id="fMonth"><option value="">전체 월</option></select>
  <select id="fHit"><option value="">전체</option><option value="2">두 팀 다 적중</option><option value="0">둘 다 빗나감</option></select></div>
 <div class="scroll"><table id="games"></table></div>
 <p class="note">막대는 득점대별 예측 확률이에요(주황 = 실제 득점대). ✔ = 모델이 가장 높게 본 득점대가 맞음.</p></div>
<p class="note" id="params"></p>
</main>
<script>
const D=__DATA__;const B=D.bins;
const binOf=x=>x<=1?0:x<=3?1:x<=5?2:x<=7?3:x<=9?4:5;
const argmax=a=>a.indexOf(Math.max(...a));
document.getElementById('season').textContent=D.season;
const sides=[];D.games.forEach(g=>{["home","away"].forEach(s=>{const o=s=="home"?"away":"home";const y=g[s+"_final"],b=binOf(y);
 sides.push({team:g[s],opp:g[o],month:g.date.slice(5,7),mu:g["mu_"+s],y,b,p:g[s+"_bins"],base:g.base,hit:argmax(g[s+"_bins"])==b})})});
const n=sides.length,mean=f=>sides.reduce((a,x)=>a+f(x),0)/n;
const mae=mean(x=>Math.abs(x.mu-x.y)),hit=mean(x=>x.hit),ll=mean(x=>-Math.log(Math.max(x.p[x.b],1e-9))),llb=mean(x=>-Math.log(Math.max(x.base[x.b],1e-9)));
const both=D.games.filter(g=>argmax(g.home_bins)==binOf(g.home_final)&&argmax(g.away_bins)==binOf(g.away_final)).length;
const gp=D.games.reduce((a,g)=>a+g.home_bins[binOf(g.home_final)]*g.away_bins[binOf(g.away_final)],0)/D.games.length;
const tiles=[["경기 수",D.games.length+"경기","팀 득점 "+n+"개"],["팀 득점 평균 오차",mae.toFixed(2)+"점","예상 득점 vs 실제"],
 ["득점대 적중률",(hit*100).toFixed(1)+"%","모델이 가장 높게 본 칸 (무작위 16.7%)"],["두 팀 동시 적중",both+"경기",(both/D.games.length*100).toFixed(1)+"%"],
 ["리그 평균 대비",((1-Math.exp(llb-ll))*-100).toFixed(1)+"%",ll<llb?"실제 결과에 준 확률이 더 높음":"리그 평균보다 못함"]];
document.getElementById('tiles').innerHTML=tiles.map(t=>`<div class="tile"><div class="k">${t[0]}</div><div class="v">${t[1]}</div><div class="n">${t[2]}</div></div>`).join("");
// calibration
(function(){const W=480,H=220,pl=34,pb=24,pt=10;const pred=B.map((_,i)=>mean(x=>x.p[i])),act=B.map((_,i)=>mean(x=>x.b==i));
 const mx=Math.ceil(Math.max(...pred,...act)*10)/10,y=v=>pt+(H-pt-pb)*(1-v/mx),bw=(W-pl)/B.length;let s=`<svg viewBox="0 0 ${W} ${H}" width="100%">`;
 for(let t=0;t<=mx+1e-9;t+=0.1){s+=`<line x1="${pl}" x2="${W}" y1="${y(t)}" y2="${y(t)}" stroke="var(--line)"/><text x="${pl-4}" y="${y(t)+4}" text-anchor="end">${Math.round(t*100)}%</text>`}
 B.forEach((l,i)=>{const x=pl+i*bw;s+=`<rect x="${x+bw*.15}" y="${y(pred[i])}" width="${bw*.33}" height="${y(0)-y(pred[i])}" fill="var(--acc)" rx="2"><title>예측 ${(pred[i]*100).toFixed(1)}%</title></rect>`;
 s+=`<rect x="${x+bw*.52}" y="${y(act[i])}" width="${bw*.33}" height="${y(0)-y(act[i])}" fill="var(--acc2)" rx="2"><title>실제 ${(act[i]*100).toFixed(1)}%</title></rect><text x="${x+bw/2}" y="${H-6}" text-anchor="middle">${l}</text>`});
 document.getElementById('calib').innerHTML=s+"</svg>"})();
// monthly
(function(){const ms=[...new Set(sides.map(x=>x.month))].sort();const W=480,H=220,pl=34,pr=40,pb=24,pt=10;
 const m=ms.map(k=>{const a=sides.filter(x=>x.month==k);return{k,mae:a.reduce((s,x)=>s+Math.abs(x.mu-x.y),0)/a.length,hit:a.filter(x=>x.hit).length/a.length,n:a.length/2}});
 const y1=v=>pt+(H-pt-pb)*(1-v/4),y2=v=>pt+(H-pt-pb)*(1-v/0.4),x=i=>pl+(W-pl-pr)*(ms.length==1?.5:i/(ms.length-1));let s=`<svg viewBox="0 0 ${W} ${H}" width="100%">`;
 [0,1,2,3,4].forEach(t=>{s+=`<line x1="${pl}" x2="${W-pr}" y1="${y1(t)}" y2="${y1(t)}" stroke="var(--line)"/><text x="${pl-4}" y="${y1(t)+4}" text-anchor="end">${t}</text><text x="${W-pr+4}" y="${y1(t)+4}">${t*10}%</text>`});
 const path=(f,c)=>`<polyline fill="none" stroke="${c}" stroke-width="2.5" points="${m.map((d,i)=>x(i)+","+f(d)).join(" ")}"/>`+m.map((d,i)=>`<circle cx="${x(i)}" cy="${f(d)}" r="3.5" fill="${c}"/>`).join("");
 s+=path(d=>y1(d.mae),"var(--acc)")+path(d=>y2(d.hit),"var(--acc2)");
 m.forEach((d,i)=>{s+=`<text x="${x(i)}" y="${H-6}" text-anchor="middle">${+d.k}월</text><rect x="${x(i)-12}" y="${pt}" width="24" height="${H-pt-pb}" fill="transparent"><title>${+d.k}월 ${d.n}경기 · 오차 ${d.mae.toFixed(2)} · 적중 ${(d.hit*100).toFixed(1)}%</title></rect>`});
 document.getElementById('monthly').innerHTML=s+"</svg>"})();
// teams
(function(){const t={};sides.forEach(x=>{(t[x.team]=t[x.team]||[]).push(x)});
 const rows=Object.entries(t).map(([k,a])=>({k,n:a.length,mu:a.reduce((s,x)=>s+x.mu,0)/a.length,y:a.reduce((s,x)=>s+x.y,0)/a.length,mae:a.reduce((s,x)=>s+Math.abs(x.mu-x.y),0)/a.length,hit:a.filter(x=>x.hit).length/a.length})).sort((a,b)=>a.mae-b.mae);
 document.getElementById('teams').innerHTML=`<tr><th class="l">팀</th><th>경기</th><th>예상 득점 평균</th><th>실제 득점 평균</th><th>차이</th><th>평균 오차</th><th>득점대 적중</th></tr>`+
 rows.map(r=>`<tr><td class="l">${r.k}</td><td>${r.n}</td><td>${r.mu.toFixed(2)}</td><td>${r.y.toFixed(2)}</td><td style="color:${Math.abs(r.y-r.mu)>.3?(r.y>r.mu?'var(--good)':'var(--bad)'):'inherit'}">${(r.y-r.mu>=0?"+":"")+(r.y-r.mu).toFixed(2)}</td><td>${r.mae.toFixed(2)}</td><td>${(r.hit*100).toFixed(1)}%</td></tr>`).join("")})();
// games
const bar=(p,b)=>`<span class="bar">${p.map((v,i)=>`<i class="${i==b?"act":""}" style="height:${Math.max(2,v*44)}px" title="${B[i]} ${(v*100).toFixed(0)}%"></i>`).join("")}</span>`;
const teams=[...new Set(sides.map(x=>x.team))].sort(),months=[...new Set(sides.map(x=>x.month))].sort();
fTeam.innerHTML+=teams.map(t=>`<option>${t}</option>`).join("");fMonth.innerHTML+=months.map(m=>`<option value="${m}">${+m}월</option>`).join("");
function draw(){const T=fTeam.value,M=fMonth.value,Hh=fHit.value;
 const rows=D.games.filter(g=>(!T||g.home==T||g.away==T)&&(!M||g.date.slice(5,7)==M)).map(g=>{const hb=binOf(g.home_final),ab=binOf(g.away_final),hh=argmax(g.home_bins)==hb,ah=argmax(g.away_bins)==ab;return{g,hb,ab,hh,ah,c:hh+ah}}).filter(r=>Hh===""||(Hh=="2"?r.c==2:r.c==0)).reverse();
 games.innerHTML=`<tr><th class="l">날짜</th><th class="l">경기 (홈 vs 원정)</th><th class="l">선발</th><th>예상</th><th>실제</th><th class="l">홈 득점대</th><th class="l">원정 득점대</th></tr>`+
 rows.map(({g,hb,ab,hh,ah})=>`<tr><td class="l">${g.date.slice(5)}</td><td class="l">${g.home} vs ${g.away} <span class="miss">@${g.stadium}</span></td><td class="l miss">${g.home_sp} / ${g.away_sp}</td>
 <td>${g.mu_home.toFixed(1)} : ${g.mu_away.toFixed(1)}</td><td><b>${g.home_final} : ${g.away_final}</b></td>
 <td class="l">${bar(g.home_bins,hb)} <span class="${hh?"hit":"miss"}">${hh?"✔":""} ${B[hb]}</span></td><td class="l">${bar(g.away_bins,ab)} <span class="${ah?"hit":"miss"}">${ah?"✔":""} ${B[ab]}</span></td></tr>`).join("")}
[fTeam,fMonth,fHit].forEach(e=>e.onchange=draw);draw();
document.getElementById('params').textContent="설정값: "+Object.entries(D.params).map(([k,v])=>k+"="+v).join(" · ");
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="kbo_games.csv")
    ap.add_argument("--season", type=int)
    ap.add_argument("--out", default="backtest_kbo.html")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    games = P.load(args.data)
    season = args.season or max(g["season"] for g in games)
    recs = records(games, season)
    out = pathlib.Path(args.out).resolve()
    out.write_text(build_html(recs, season), encoding="utf-8")
    print(f"리포트 저장: {out}  ({len(recs)}경기)")
    if not args.no_open:
        webbrowser.open(out.as_uri())


if __name__ == "__main__":
    main()
