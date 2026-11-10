"""배구 예측기 테스트.  python -m unittest test_vb -v"""
import unittest


def _game(gnum, hcode, acode, score, league="201", hname="홈", aname="원정", sets=None):
    sets = sets or ([25, 23, 25, 25, 0], [20, 25, 22, 21, 0])
    hs, as_ = (int(score[0]), int(score[-1])) if score else (0, 0)
    g = {"seasonCode": "023", "leagueCode": league, "gender": hcode[0], "gnum": gnum,
         "hcode": hcode, "hname": hname, "acode": acode, "aname": aname,
         "gdate": "2026-11-01", "hspoint": hs, "aspoint": as_, "score": score}
    for i in range(5):
        g[f"hs{i+1}point"] = sets[0][i] if score else 0
        g[f"as{i+1}point"] = sets[1][i] if score else 0
    return g


class FetchTest(unittest.TestCase):
    def test_season_name(self):
        import vb_fetch
        self.assertEqual(vb_fetch.season_name("023"), "2026-27")
        self.assertEqual(vb_fetch.season_name("020"), "2023-24")

    def test_rows_from_json(self):
        import vb_fetch
        data = {"payload": {"content": [
            _game(1, "1005", "1001", "3 : 1"),
            _game(2, "1005", "1001", "3 : 0", league="803"),
            _game(3, "1002", "1006", ""),
        ]}}
        rows = vb_fetch.rows_from_json(data)
        self.assertEqual(len(rows), 2)
        first = next(r for r in rows if r["gnum"] == 1)
        self.assertEqual(first["home"], "현대캐피탈")
        self.assertEqual(first["away"], "대한항공")
        self.assertEqual(first["season"], "2026-27")
        self.assertEqual(first["home_sets"], 3)
        self.assertEqual(first["h1"], 25)
        self.assertEqual(first["played"], 1)
        self.assertEqual(next(r for r in rows if r["gnum"] == 3)["played"], 0)

    def test_unknown_team_code_keeps_hname(self):
        import vb_fetch
        rows = vb_fetch.rows_from_json({"payload": {"content": [_game(1, "1999", "1001", "3 : 1", hname="새팀")]}})
        self.assertEqual(rows[0]["home"], "새팀")

    def test_merge_overwrites_and_dedups(self):
        import vb_fetch
        old = vb_fetch.rows_from_json({"payload": {"content": [_game(5, "1005", "1001", "")]}})
        new = vb_fetch.rows_from_json({"payload": {"content": [_game(5, "1005", "1001", "3 : 1")]}})
        merged = vb_fetch.merge_rows(old, new)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["played"], 1)


def _row(date, home, away, hpts, apts, season="2026-27", gender="1", hs=3, as_=1, played=1, gnum=None):
    """끝난 경기 한 줄 (세트별 점수는 1세트에 몰아서 넣어 득점률만 맞춤)."""
    _row.n = getattr(_row, "n", 0) + 1
    return {"date": date, "season": season, "gender": gender, "gnum": gnum or _row.n,
            "home": home, "away": away, "home_sets": hs, "away_sets": as_,
            "h1": hpts, "h2": 0, "h3": 0, "h4": 0, "h5": 0, "a1": apts, "a2": 0, "a3": 0, "a4": 0, "a5": 0,
            "played": played}


class ModelTest(unittest.TestCase):
    def test_set_prob_half(self):
        import predict_vb as P
        self.assertAlmostEqual(P.set_win_prob(0.5, 25), 0.5, places=9)
        self.assertAlmostEqual(P.set_win_prob(0.5, 15), 0.5, places=9)

    def test_set_prob_symmetric_monotonic(self):
        import predict_vb as P
        self.assertAlmostEqual(P.set_win_prob(0.53, 25) + P.set_win_prob(0.47, 25), 1.0, places=9)
        a, b, c = (P.set_win_prob(p, 25) for p in (0.50, 0.52, 0.55))
        self.assertLess(a, b)
        self.assertLess(b, c)

    def test_score_dist_sums_to_one(self):
        import predict_vb as P
        for s in (0.0, 0.3):
            d = P.score_dist(0.53, sigma=s)
            self.assertEqual(set(d), set(P.SCORES))
            self.assertAlmostEqual(sum(d.values()), 1.0, places=6)

    def test_sigma_increases_sweeps(self):
        import predict_vb as P
        d0, d3 = P.score_dist(0.53, sigma=0.0), P.score_dist(0.53, sigma=0.3)
        self.assertGreater(d3[(3, 0)] + d3[(0, 3)], d0[(3, 0)] + d0[(0, 3)])

    def test_ratings_mean_zero_and_order(self):
        import predict_vb as P
        games = [_row("2026-11-01", "A", "B", 110, 95), _row("2026-11-02", "B", "C", 105, 98),
                 _row("2026-11-03", "C", "A", 90, 108), _row("2026-11-04", "A", "C", 100, 92)]
        r, n = P.team_ratings(games)
        self.assertAlmostEqual(sum(r.values()), 0.0, places=9)
        self.assertGreater(r["A"], r["B"])
        self.assertGreater(r["B"], r["C"])
        self.assertEqual(n["A"], 3)

    def test_ratings_skip_zero_points(self):
        import predict_vb as P
        games = [_row("2026-11-01", "A", "B", 110, 95), _row("2026-11-02", "B", "A", 100, 98)]
        r1, n1 = P.team_ratings(games)
        r2, n2 = P.team_ratings(games + [_row("2026-11-03", "A", "B", 0, 0)])
        self.assertEqual(r1, r2)
        self.assertEqual(n1, n2)

    def test_blend_new_team(self):
        import predict_vb as P
        self.assertEqual(P.blend(0.0, 0, 0.0), 0.0)
        w = 8 / (8 + P.K)
        self.assertAlmostEqual(P.blend(0.2, 8, 0.1), w * 0.2 + (1 - w) * P.REGRESS * 0.1)


if __name__ == "__main__":
    unittest.main()
