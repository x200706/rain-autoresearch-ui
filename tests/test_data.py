from conftest import make_csv, make_station
from rainui import charts, results, stations


def test_station_choices_list_completed_and_not_started(rain_root):
    make_station(rain_root, "467590")
    make_station(rain_root, "467650", complete=False)
    make_csv(rain_root / "data" / "467350.csv")
    choices = dict((sid, text) for text, sid in stations.station_choices())
    assert choices["467590"].endswith("（已完成）")
    assert choices["467650"].endswith("（未完成）")
    assert choices["467350"].endswith("（尚未實驗）")
    assert stations.completed_stations() == ["467590"]


def test_uploaded_file_is_not_listed_as_a_station(rain_root, tmp_path):
    upload = make_csv(tmp_path / "upload" / "466930.csv")
    stations.check_csv(upload)
    assert "466930" not in [sid for _, sid in stations.station_choices()]


def test_check_csv_reports_problems(tmp_path):
    good = stations.check_csv(make_csv(tmp_path / "466930.csv"))
    assert good.ok and good.station == "466930" and good.rows == 5 and good.hours_at_least(40) == 1
    no_id = stations.check_csv(make_csv(tmp_path / "rain.csv"))
    assert any("6 碼站號" in e for e in no_id.errors)
    bad_cols = stations.check_csv(make_csv(tmp_path / "466930b.csv", header=("時間", "雨量")))
    assert any("找不到欄位" in e for e in bad_cols.errors)


def test_load_station_reads_results_and_stats(rain_root):
    make_station(rain_root, "467590")
    st = results.load_station("467590")
    s = results.stats(st, "under")
    assert s["best_run"] == "g02_c1" and s["mae"] == 12.0 and s["g1"]["mae_ge40mm"] == 30.0
    assert s["control"]["mae_ge40mm"] == 40.0 and s["runs"] == 2
    table = results.results_table(st, "under")
    assert list(table["run"]) == ["g01_c1", "g02_c1"]
    assert table.loc[0, "α"] == "WMAE 原始研究" and table.loc[1, "狀態"] == "★ best"
    assert results.generation_choices(st, "under") == ["全部", "第 1 代", "第 2 代"]
    assert list(results.results_table(st, "under", "第 2 代")["run"]) == ["g02_c1"]


def test_results_refresh_when_files_change(rain_root):
    sd = make_station(rain_root, "467590")
    assert results.load_station("467590")["learnings"].startswith("# 學習紀錄")
    import os
    import time
    (sd / "learnings.md").write_text("# 新的學習紀錄\n", encoding="utf-8")
    later = time.time() + 5
    os.utime(sd / "learnings.md", (later, later))
    assert results.load_station("467590")["learnings"].startswith("# 新的學習紀錄")


def test_predictions_drop_only_inner_zero_points(rain_root):
    make_station(rain_root, "467590")
    st = results.load_station("467590")
    frame = results.predictions(st["subgoals"]["under"]["artifact"], "train")
    # 6 筆：開頭 3 個 0 留頭尾、5/3 那筆、最後 2 個 0 都是頭尾 → 只少掉中間那一個 0
    assert len(frame) == 5 and frame["actual"].max() == 5


def test_prediction_chart_uses_plain_lists_not_binary_arrays(rain_root):
    make_station(rain_root, "467590")
    st = results.load_station("467590")
    fig = charts.predictions(results.predictions(st["subgoals"]["under"]["artifact"], "test"), "測試集")
    assert "bdata" not in fig.to_json()
    names = [t.name for t in fig.data]
    assert names[0] == "觀測雨量" and names[1].startswith("預測雨量")     # 預測畫在觀測上面
    conv = charts.convergence(st["subgoals"]["under"]["conv"])
    assert conv.layout.xaxis.fixedrange and conv.layout.yaxis.fixedrange and conv.layout.dragmode is False


def test_results_table_calls_failed_runs_subgoal_intercepts(rain_root):
    make_station(rain_root, "467590")
    st = results.load_station("467590")
    st["subgoals"]["under"]["rows"][1]["status"] = "guard_fail"
    st["subgoals"]["under"]["best_run"] = "g01_c1"
    assert results.results_table(st, "under").loc[1, "狀態"] == "副目標攔截"


def test_bundle_fallback_when_no_outputs(monkeypatch, tmp_path):
    monkeypatch.setenv("RAIN_AUTORESEARCH_ROOT", str(tmp_path / "missing"))
    results.load_bundle.cache_clear()
    st = results.load_station("467590")
    assert st is not None and st["subgoals"]["under"]["best_run"]
