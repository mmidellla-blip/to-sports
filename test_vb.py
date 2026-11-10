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


if __name__ == "__main__":
    unittest.main()
