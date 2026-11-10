# V리그 승패·세트스코어 예측기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** KOVO 정규리그 기록으로 남/여 경기의 승패와 세트스코어 6칸 확률을 내고, 백테스트를 콘솔과 HTML로 보여준다.

**Architecture:** `vb_fetch.py`가 KOVO JSON을 `vb_games.csv`로 바꾸고, `predict_vb.py`가 득점률 로짓 레이팅 → 랠리 승률 → 세트 승률(정확식) → 세트스코어(+경기 컨디션 흔들림 적분)를 계산하며 `--backtest`를 제공한다. `report_vb.py`는 `predict_vb`의 백테스트 기록을 정적 HTML로 만든다 (농구 `report.py`가 `predict`를 import하는 방식과 같음).

**Tech Stack:** Python 3.11, 표준 라이브러리 + numpy(가우스-에르미트 적분) + requests(다운로드만). 테스트는 `unittest` (pytest 미설치).

**Spec:** `docs/superpowers/specs/2026-11-10-volleyball-predictor-design.md`

## Global Constraints

- 정규리그만: `leagueCode=201`. 시즌 코드 `020`=2023-24, `021`=2024-25, `022`=2025-26, `023`=2026-27 (코드 = 시즌 시작 연도 − 2003, 3자리).
- 시즌 이름 형식은 `2026-27` (농구 `games.csv`와 같음).
- 조정값 기본: `K=8`, `REGRESS=0.4`, `SCALE=1.2`, `SIGMA=0.2`, `HOME` = 직전 시즌 홈 랠리 득점률의 로짓.
- 백테스트는 그 경기 **날짜보다 앞선** 경기만 쓴다 (같은 날 경기 제외).
- 다운로드: 요청 사이 1초 이상 쉼, `User-Agent: Mozilla/5.0`만 보낸다 (Origin/Referer 흉내 내지 않음).
- 출력 문구는 한국어, 기존 예측기 말투(`~해요`)를 따른다. 콘솔 출력은 `sys.stdout.reconfigure(encoding="utf-8")`.
- 팀 짧은 이름 (코드 → 이름):
  남 `1001 대한항공` `1002 삼성화재` `1004 KB손해보험` `1005 현대캐피탈` `1006 한국전력` `1008 OK저축은행` `1009 우리카드`
  여 `2001 현대건설` `2002 한국도로공사` `2003 정관장` `2004 흥국생명` `2005 GS칼텍스` `2006 IBK기업은행` `2007 페퍼저축은행` `2008 SOOP`

## Review Focus

1. 신생 팀(`2008 SOOP`, 지난 시즌 기록 없음) → 레이팅 기본값 0으로 예측돼야 하고 오류가 나면 안 됨. (Task 2 테스트)
2. 시즌 첫 경기(이번 시즌 기록 0경기) 백테스트 → 지난 시즌 레이팅×REGRESS만으로 예측. (Task 3 테스트)
3. 같은 날 두 경기 → 서로의 결과를 쓰면 안 됨 (누수). (Task 3 테스트)
4. `vb_fetch.py`를 두 번 실행 → `vb_games.csv`에 같은 경기가 중복되면 안 되고, 예정 경기가 끝나면 덮어써져야 함. (Task 1 테스트)
5. 끝난 경기인데 세트별 점수 합이 0 → 득점률 계산에서 빠지고 세트스코어 평가에는 남음. (Task 2 테스트)

---

### Task 1: `vb_fetch.py` — JSON → `vb_games.csv`

**Files:**
- Create: `vb_fetch.py`
- Create: `test_vb.py` (이 태스크에서 `FetchTest` 클래스)
- Modify: `README.md` (배구 절 추가: 수집·예측·백테스트·리포트 명령)

**Interfaces:**
- Produces:
  - `TEAM_NAMES: dict[str, str]` (Global Constraints 표)
  - `season_name(code: str) -> str` — `"023"` → `"2026-27"`
  - `rows_from_json(data: dict) -> list[dict]` — `payload.content`에서 `leagueCode=="201"`만, 칸은 아래 CSV 순서. 이름은 `TEAM_NAMES.get(code, hname)`.
  - `merge_rows(existing: list[dict], new: list[dict]) -> list[dict]` — 키 `(season, gender, gnum)`, new가 이김, `(date, gender, gnum)` 정렬
  - CSV 칸: `date,season,gender,gnum,home,away,home_sets,away_sets,h1,h2,h3,h4,h5,a1,a2,a3,a4,a5,played` (`gender` "1"/"2", `played` 1 = `score`가 비어 있지 않음)
  - CLI: `python vb_fetch.py 023 [022 ...]` (다운로드 → `kovo_XXX.json` 저장 → 병합), `python vb_fetch.py --from-json kovo_021.json ...`, 출력 파일 `--out vb_games.csv`

- [ ] **Step 1: 실패하는 테스트 작성** (`test_vb.py`, `class FetchTest(unittest.TestCase)`)
  - `test_season_name`: `season_name("023") == "2026-27"`, `season_name("020") == "2023-24"`
  - `test_rows_from_json`: 남 1경기(정규, `score "3 : 1"`, 세트 점수 채움) + 컵대회 1경기(`leagueCode "803"`) + 예정 1경기(`score ""`)로 만든 dict → 결과 2행, 첫 행 `home == "현대캐피탈"`(hcode 1005), `home_sets == 3`, `played == 1`, 예정 행 `played == 0`
  - `test_unknown_team_code_keeps_hname`: hcode `"1999"`, hname `"새팀"` → `home == "새팀"`
  - `test_merge_overwrites_and_dedups`: 예정 행 + 같은 키의 끝난 행 병합 → 1행, `played == 1`

- [ ] **Step 2: 실패 확인** — Run: `python -m unittest test_vb.FetchTest -v` / Expected: `ModuleNotFoundError: No module named 'vb_fetch'`

- [ ] **Step 3: `vb_fetch.py` 구현** — 위 Interfaces 그대로. 다운로드 URL `https://user-api.kovo.co.kr/stat/game-schedule?seasonCode={code}&leagueCode=201&size=1000&page=0`, `requests.get(..., headers={"User-Agent": "Mozilla/5.0"}, timeout=15)`, 실패하면 브라우저 F12 → Network → `game-schedule` 응답을 `kovo_XXX.json`으로 저장 후 `--from-json` 쓰라고 안내하고 종료 코드 1. `truststore`는 `kbl_scores.py`처럼 있으면 주입.

- [ ] **Step 4: 통과 확인** — Run: `python -m unittest test_vb.FetchTest -v` / Expected: 4 tests OK

- [ ] **Step 5: 실제 데이터 변환** — Run: `python vb_fetch.py --from-json kovo_020.json kovo_021.json kovo_022.json kovo_023.json` / Expected: `vb_games.csv` 1008행, 끝난 경기 772 (252×3 + 16)

- [ ] **Step 6: README 배구 절 추가 후 커밋**
```bash
git add vb_fetch.py test_vb.py README.md vb_games.csv
git commit -m "배구: KOVO 정규리그 수집기와 vb_games.csv"
```

---

### Task 2: `predict_vb.py` 계산 핵심

**Files:**
- Create: `predict_vb.py`
- Modify: `test_vb.py` (`ModelTest` 클래스)

**Interfaces:**
- Consumes: `vb_games.csv` 형식 (Task 1)
- Produces:
  - 상수 `K=8`, `REGRESS=0.4`, `SCALE=1.2`, `SIGMA=0.2`, `SCORES = [(3,0),(3,1),(3,2),(2,3),(1,3),(0,3)]`
  - `load_games(path="vb_games.csv") -> list[dict]` — 숫자 칸 int 변환, `date` 문자열 `YYYY-MM-DD`
  - `set_win_prob(p: float, target: int) -> float` — target점 선승, 듀스 이후 `p²/(p²+q²)`
  - `score_dist(p_rally: float, sigma: float = SIGMA) -> dict[tuple[int,int], float]` — sigma=0이면 독립 세트식, 아니면 로짓에 `N(0, sigma)`를 더해 `numpy.polynomial.hermite_e.hermegauss(15)` 가중 평균
  - `team_ratings(games: list[dict]) -> tuple[dict[str, float], dict[str, int]]` — 끝난 경기 중 세트 점수 합 > 0인 것만, 상대 보정 20회 반복, 평균 0으로 맞춤. (레이팅, 경기 수)
  - `home_logit(games: list[dict]) -> float` — 홈 랠리 득점률의 로짓
  - `blend(cur: float, n: int, prior: float) -> float` — `w=n/(n+K)`, `w*cur + (1-w)*REGRESS*prior`

- [ ] **Step 1: 실패하는 테스트 작성** (`class ModelTest`)
  - `test_set_prob_half`: `set_win_prob(0.5, 25)`와 `(0.5, 15)` ≈ 0.5 (`assertAlmostEqual`, 9자리)
  - `test_set_prob_symmetric_monotonic`: p=0.53 → `set_win_prob(p,25) + set_win_prob(1-p,25) ≈ 1`; 0.50 < 0.52 < 0.55 순으로 증가
  - `test_score_dist_sums_to_one`: sigma 0과 0.3에서 6칸 합 ≈ 1, 키 집합 == `set(SCORES)`
  - `test_sigma_increases_sweeps`: p=0.53에서 `d[(3,0)]+d[(0,3)]`이 sigma 0.3 > sigma 0
  - `test_ratings_mean_zero_and_order`: 세 팀 A>B>C 가상 경기(점수로 차이 줌) → 레이팅 합 ≈ 0, A > B > C
  - `test_ratings_skip_zero_points`: 세트 점수 전부 0인 끝난 경기 하나 추가해도 레이팅 변화 없음, 경기 수에도 안 셈
  - `test_blend_new_team`: `blend(0.0, 0, 0.0) == 0.0`; `blend(0.2, 8, 0.1) == 0.5*0.2 + 0.5*0.4*0.1`

- [ ] **Step 2: 실패 확인** — Run: `python -m unittest test_vb.ModelTest -v` / Expected: `ModuleNotFoundError: No module named 'predict_vb'`

- [ ] **Step 3: 구현** — 위 시그니처. 세트 승률:
```python
q = 1 - p
s = sum(comb(target-1+k, k) * p**target * q**k for k in range(target-1))
return s + comb(2*(target-1), target-1) * p**(target-1) * q**(target-1) * p*p / (p*p + q*q)
```
세트스코어: P=25점 세트, P5=15점 세트, `3:0=P³, 3:1=3P³Q, 3:2=6P²Q²P5`, 반대쪽 대칭. 레이팅: `r_i = logit(s_i) + mean(r_opp)` 반복 후 평균 빼기.

- [ ] **Step 4: 통과 확인** — Run: `python -m unittest test_vb -v` / Expected: 11 tests OK

- [ ] **Step 5: 커밋**
```bash
git add predict_vb.py test_vb.py
git commit -m "배구: 득점률 레이팅·세트 승률·세트스코어 계산"
```

---

### Task 3: `predict_vb.py` 예측·백테스트 CLI

**Files:**
- Modify: `predict_vb.py`
- Modify: `test_vb.py` (`BacktestTest` 클래스)

**Interfaces:**
- Consumes: Task 2 전부
- Produces:
  - `prev_season(season: str) -> str` — `"2026-27"` → `"2025-26"`
  - `predict_game(games, gender, home, away, season, before_date) -> dict` — 키: `home_rating`, `away_rating`, `home_n`, `away_n`, `p_rally`, `p_set`, `p_set5`, `dist`, `p_home`. 이번 시즌 경기 중 `date < before_date`, 지난 시즌 전체로 기본값, `HOME = home_logit(지난 시즌)` (지난 시즌 없으면 0)
  - `backtest_records(games, season) -> list[dict]` — 그 시즌 끝난 경기마다 `predict_game` 결과 + `date, gender, home, away, home_sets, away_sets`
  - `summarize(records) -> dict` — `n, acc, logloss, brier, top1, score_logloss`, 확률 구간별 `calib: list[(lo, n, mean_p, hit_rate)]`
  - CLI: `--home/--away` (성별 자동, 같은 성별이 아니면 오류), `--date YYYYMMDD` (그날 `played==0` 경기 전부), `--backtest [--season 2025-26]` (기본 = 데이터의 가장 최근 시즌), `--data vb_games.csv`

- [ ] **Step 1: 실패하는 테스트 작성** (`class BacktestTest`, 가상 경기 목록으로)
  - `test_prev_season`: `prev_season("2026-27") == "2025-26"`
  - `test_first_game_uses_prior_only`: 이번 시즌 첫날 경기 → `home_n == away_n == 0`, `home_rating == REGRESS * 지난시즌 레이팅`
  - `test_same_day_no_leak`: 같은 날 두 경기 중 두 번째의 결과를 극단적으로 바꿔도 첫 번째 경기 예측이 같음
  - `test_new_team_prior_zero`: 지난 시즌에 없는 팀 → 레이팅 0, 예외 없음
  - `test_summarize_values`: 기록 2개(`p_home` 0.7 맞음 / 0.6 틀림) → `acc == 0.5`, `logloss ≈ (-ln .7 - ln .4)/2`

- [ ] **Step 2: 실패 확인** — Run: `python -m unittest test_vb.BacktestTest -v` / Expected: `AttributeError` (함수 없음)

- [ ] **Step 3: 구현** — 백테스트는 날짜별로 `team_ratings`를 한 번만 계산해 캐시. 콘솔 출력 형식은 spec "출력 예시"와 같게 (팀 줄: 지난시즌 레이팅, 이번시즌 n경기, 반영 %, 최종 레이팅 / 랠리 승률 → 세트 승률(5세트) / 승패 / 세트스코어). 백테스트 요약: spec 검증 결과 표의 4줄 + 남/여 + 확률 보정 표 + 비교 기준(동전 0.693, 무조건 홈 승률, 지난 시즌 세트스코어 비율의 로그 손실·1순위 적중). 틀린 팀 이름이면 그 성별 팀 목록 출력 후 종료 코드 1.

- [ ] **Step 4: 통과 확인** — Run: `python -m unittest test_vb -v` / Expected: 16 tests OK

- [ ] **Step 5: 실제 데이터 확인**
  - Run: `python predict_vb.py --backtest --season 2025-26` / Expected: 252경기, 승패 적중 약 60%, 세트스코어 1순위 약 25% (검증용 코드 수치와 ±2%p)
  - Run: `python predict_vb.py --home 현대캐피탈 --away 대한항공` / Expected: 6칸 합 100%, 남자부 표시
  - Run: `python predict_vb.py --home 현대캐피탈 --away 흥국생명` / Expected: 성별이 다르다는 오류

- [ ] **Step 6: 커밋**
```bash
git add predict_vb.py test_vb.py
git commit -m "배구: 예측·날짜별 경기·백테스트 CLI"
```

---

### Task 4: 조정값 확인 (`--tune`)

**Files:**
- Modify: `predict_vb.py`

**Interfaces:**
- Consumes: `backtest_records`, `summarize`
- Produces: `tune(games, season) -> list[tuple[float, dict]]` — 격자 `K∈{4,8,12,20}`, `REGRESS∈{0,0.2,0.4,0.6}`, `SCALE∈{1.0,1.2,1.5}`, `SIGMA∈{0,0.2,0.3,0.4}`, 기준 = `score_logloss` 오름차순. CLI `--tune --season 2024-25`는 상위 5개를 출력만 하고 상수는 바꾸지 않음.

- [ ] **Step 1: 구현** — 상수를 함수 인자 기본값이 아닌 모듈 전역으로 두고, `tune`은 전역을 바꿔가며 돌린 뒤 원래 값으로 되돌림 (`try/finally`).
- [ ] **Step 2: 확인** — Run: `python predict_vb.py --tune --season 2024-25` / Expected: 1위 세트스코어 로그 손실 약 1.711, 실행 후 `python -m unittest test_vb` 여전히 OK (전역 복원)
- [ ] **Step 3: 커밋** — `git commit -am "배구: 조정값 격자 탐색 --tune"`

---

### Task 5: `report_vb.py` — HTML 리포트

**Files:**
- Create: `report_vb.py`
- Modify: `.gitignore` 안 바꿈 (리포트 HTML은 농구처럼 커밋)

**Interfaces:**
- Consumes: `predict_vb.load_games`, `backtest_records`, `summarize`, `SCORES`
- Produces: `build_html(records: list[dict], summary: dict, season: str) -> str`; CLI `python report_vb.py [--season 2026-27] [--out backtest_vb.html] [--no-open]`

- [ ] **Step 1: 구현** — `report.py`의 `:root` 색 토큰·다크 모드 블록·카드 스타일을 그대로 복사. 구성: 요약 숫자 4개(승패 적중, 승패 로그 손실, 세트스코어 1순위, 세트스코어 로그 손실, 각각 비교 기준 작게), 확률 보정 표, 남/여/전체 필터 버튼(JS로 카드 숨김), 경기별 카드(날짜·팀·예측 승 확률·6칸 확률 가로 막대, 실제 세트스코어 칸 강조, 1순위가 맞으면 "적중" 표시). 최신 경기가 위. 폭 360px에서 가로 스크롤 없음.
- [ ] **Step 2: 확인** — Run: `python report_vb.py --season 2025-26 --no-open` / Expected: `리포트 저장: ...backtest_vb.html (252경기)`; 브라우저로 열어 라이트/다크, 필터, 좁은 폭 확인
- [ ] **Step 3: 이번 시즌 리포트** — Run: `python report_vb.py` / Expected: 2026-27, 16경기 (끝난 경기 수만큼)
- [ ] **Step 4: 커밋**
```bash
git add report_vb.py backtest_vb.html
git commit -m "배구: 백테스트 HTML 리포트"
```
