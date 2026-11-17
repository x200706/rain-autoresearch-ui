"""規格書列的介面 bug：用介面的事件函式直接重現。"""
import pytest

from conftest import make_csv, make_station
from rainui import skill, view

app = pytest.importorskip("app")
DEFAULTS = dict(model="deepseek/deepseek-v4.1-flash-1017", run_name="", source="existing", station="467590", upload=None,
                split="82", metric="mae", thr=40, sub_mode="preset", subs=["under", "total", "rmse"], sub_text="",
                max_gen=20, patience=3, children=8, parallel=3, template=skill.DEFAULT_TEMPLATE)


def left(**kw):
    values = {**DEFAULTS, **kw}
    return list(values.values())


def start_label(out):
    return out[11]["value"]


def test_completed_station_shows_cache_hit_regardless_of_what_is_viewed(rain_root):
    make_station(rain_root, "467590")
    make_station(rain_root, "466910")
    out = app.refresh_left("", *left())
    assert start_label(out) == "Cache Hit・展示快取結果" and out[12] == "st:467590"
    for key in ("st:466910", "st:467590"):                 # 切換主畫面不會影響左側的判斷
        app.render_view(key, "under", "train", "全部")
        assert start_label(app.refresh_left("", *left())) == "Cache Hit・展示快取結果"
    assert start_label(app.refresh_left("", *left(thr=30))) == "開始訓練"


def test_bad_file_blocks_and_switching_source_clears_it(rain_root, tmp_path):
    make_station(rain_root, "467590")
    bad = app.file_state(str(make_csv(tmp_path / "466930.csv", header=("時間", "雨量"))))
    cfg, err = app.make_config(*left(source="codis", upload=bad))
    assert err and skill.blocking(skill.field_errors(cfg, "", err))
    # 改回「已抓取」：抓到的檔案被清掉，不會偷偷留著，也不會把新站加進選單
    station_update, state, row, btn = app.on_source("existing")
    assert state is None and station_update["visible"] and not row["visible"] and not btn["visible"]
    cfg, err = app.make_config(*left(source="existing", upload=None))
    assert not err and cfg.station == "467590"


def test_codis_mode_never_uses_the_dropdown_station(rain_root, tmp_path):
    make_station(rain_root, "467590")
    good = app.file_state(str(make_csv(tmp_path / "466930.csv")))
    cfg, err = app.make_config(*left(source="codis", upload=good, station="467590"))
    assert cfg.station == "466930" and not err
    cfg, err = app.make_config(*left(source="codis", upload=None, station="467590"))
    assert cfg.station == "" and err == "請先從 CoDiS 抓取資料"
    assert "466930" not in [sid for _, sid in app.stations.station_choices()]


def test_station_without_heavy_rain_blocks(rain_root, tmp_path):
    dry = app.file_state(str(make_csv(tmp_path / "466930.csv", rain=(0, 1, 2))))
    _, err = app.make_config(*left(source="codis", upload=dry))
    assert "≥ 40 mm" in err


def test_history_lists_runs_with_names_and_finished_stations_as_tags(rain_root):
    make_station(rain_root, "467590")
    run = app.runner.start_run(skill.RunConfig(station="466930", run_name="竹子湖 第一次", model="m"), mode="demo")
    items = view.history_items()
    assert items[0]["title"] == "竹子湖 第一次"
    assert ("466930 竹子湖", "station") in items[0]["tags"] and ("展示中", "run") in items[0]["tags"]
    assert items[1]["title"] == "467590 恆春" and ("完成", "ok") in items[1]["tags"]
    assert [it["key"] for it in view.history_items("竹子湖")] == [f"run:{run['id']}"]
    html = view.history_html(items, "st:467590")
    assert html.count('class="hist-card"') == 2 and 'data-hist="st:467590" aria-current="true"' in html
    assert 'class="tag tag-ok">完成' in html


def test_download_button_points_at_the_current_skill(rain_root):
    make_station(rain_root, "467590")
    link = app.refresh_left("", *left(thr=30))[13]
    assert 'download="SKILL.md"' in link and "gradio_api/file=" in link
    text = (app.config.state_dir() / "downloads" / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: rain-autoresearch-467590") and "rmse" in text and "≥ 30 mm" in text
    assert "介面覆寫" in text


def test_wording_uses_subgoal_not_gate(rain_root):
    make_station(rain_root, "467590")
    st = app.results.load_station("467590")
    stats = view.stats_html(st, "under")
    assert "未經較佳化兩階段分類器對照 ≥ 40 mm MAE" in stats and "守門" not in stats and "第 1 代 / 純 MAE" not in stats
    assert all(label.startswith("副目標：") for label, _ in view.sub_tab_choices())
    assert "AE ≥ 20 mm" in view.sub_tab_choices()[0][0]
    assert "守門" not in skill.render(skill.RunConfig(station="467590"))


def test_render_view_for_station_and_running_demo(rain_root):
    make_station(rain_root, "467590")
    out = app.render_view("st:467590", "total", "test", "全部")
    assert "467590 恆春" in out[0] and out[4]["visible"] and "g02_c1" in out[5]
    run = app.runner.start_run(skill.RunConfig(station="466930", run_name="竹子湖", model="m"), mode="demo")
    out = app.render_view(f"run:{run['id']}", "under", "train", "全部")
    assert "class=\"flow\"" in out[2] and not out[4]["visible"]


def test_delete_run_and_station(rain_root):
    make_station(rain_root, "467590")
    run = app.runner.start_run(skill.RunConfig(station="466930", run_name="竹子湖", model="m"), mode="demo")
    app.runner.delete_run(run["id"])
    assert app.runner.get_run(run["id"]) is None
    assert app.runner.delete_station("467590") is True
    assert not (rain_root / "outputs" / "467590").exists() and not (rain_root / "outputs" / "_deleted").exists()
    assert app.runner.delete_station("467590") is False
    assert "467590" not in [sid for _, sid in app.stations.station_choices()]


def test_project_path_can_be_changed_and_is_checked(rain_root, tmp_path):
    from rainui import config
    try:
        assert "program.md" in config.set_rain_root(str(tmp_path / "nowhere"))
        assert config.rain_root() == rain_root
        other = tmp_path / "other_root"
        (other / "outputs").mkdir(parents=True)
        (other / "program.md").write_text("x", encoding="utf-8")
        assert config.set_rain_root(str(other)) == ""
        assert config.rain_root() == other
    finally:
        config.set_rain_root("")


def test_skill_preview_hides_frontmatter_and_page_has_no_real_mode_label(rain_root):
    make_station(rain_root, "467590")
    out = app.render_view("st:467590", "under", "train", "全部")
    assert not out[13].startswith("---") and "name: rain-autoresearch" not in out[13]
    assert skill.strip_frontmatter(skill.skill_markdown(skill.RunConfig(station="1"))).startswith("# Rain Autoresearch")
    assert "真實模式" not in app.footer_html()


def test_delete_asks_first_and_names_the_target(rain_root):
    make_station(rain_root, "467590")
    demo = app.build()
    ask = next(fn for fn in (demo.fns.values() if isinstance(demo.fns, dict) else demo.fns)
               if getattr(fn.fn, "__name__", "") == "ask_delete").fn
    row, text, pending = ask("st:467590")
    assert row["visible"] and pending == "st:467590" and "467590 恆春" in text and "無法復原" in text
    assert (rain_root / "outputs" / "467590").exists()          # 只顯示確認列，還沒刪


def test_automatic_station_file_name_is_accepted(rain_root, tmp_path):
    """自動站代碼英數混合（C0A870），和有人站一樣可以用。"""
    good = app.file_state(str(make_csv(tmp_path / "C0A870.csv")))
    cfg, err = app.make_config(*left(source="codis", upload=good))
    assert cfg.station == "C0A870" and not err
    assert not app.stations.check_csv(make_csv(tmp_path / "report.csv")).station


def test_start_button_names_what_blocks_it(rain_root):
    """副目標全部取消勾選時，按鈕本身寫出原因，不只欄位下方的紅字。"""
    make_station(rain_root, "467590")
    assert start_label(app.refresh_left("", *left(subs=[]))) == "無法開始：至少勾一種副目標"


def test_codis_source_needs_a_download_first(rain_root, tmp_path, monkeypatch):
    make_station(rain_root, "467590")
    cfg, err = app.make_config(*left(source="codis", upload=None, station="467590"))
    assert cfg.station == "" and err == "請先從 CoDiS 抓取資料"
    csv_path = make_csv(tmp_path / "466910.csv")
    monkeypatch.setattr(app.sources, "codis_download", lambda sid, progress=None: str(csv_path))
    monkeypatch.setattr(app.sources, "name_of", lambda sid: "鞍部")
    got = app.on_codis_download("466910", progress=lambda *a, **k: None)
    assert got["station"] == "466910" and not got["errors"] and "鞍部" in got["name"] and "CoDiS" in got["name"]
    cfg, err = app.make_config(*left(source="codis", upload=got, station="467590"))
    assert cfg.station == "466910" and not err


def test_codis_without_data_says_the_station_cannot_be_used(monkeypatch):
    from rainui import codis
    monkeypatch.setattr(codis, "fetch", lambda *a, **k: codis.pd.DataFrame(columns=["觀測時間(hour)", *codis.COLUMNS]))
    monkeypatch.setattr(app.gr, "Warning", lambda *a, **k: None)
    got = app.on_codis_download("C1Z999", progress=lambda *a, **k: None)
    assert got["errors"] == ["CoDiS 沒有 C1Z999 的資料，這個測站不能用"]


def test_codis_download_fetches_month_by_month(monkeypatch, tmp_path):
    from rainui import codis, sources
    monkeypatch.setenv("RAIN_UI_STATE_DIR", str(tmp_path))
    calls = []

    def fake(station, start, end, kind="", stypes=None):
        calls.append((start, end))
        hours = codis.pd.date_range(codis.pd.Timestamp(start).floor("h"), codis.pd.Timestamp(end).floor("h"), freq="h")
        return codis.pd.DataFrame({"觀測時間(hour)": hours, "降水量(mm)": 0.0})
    monkeypatch.setattr(codis, "fetch", fake)
    path = sources.codis_download("466910", end=codis.pd.Timestamp("2009-03-15"))
    frame = codis.pd.read_csv(path, encoding="utf-8-sig")
    assert frame["觀測時間(hour)"].iloc[0] == "2009-01-01 00:00:00" and frame["觀測時間(hour)"].iloc[-1] == "2009-03-15 00:00:00"
    assert frame["觀測時間(hour)"].is_unique and len(frame) == (31 + 28 + 14) * 24 + 1


def test_fetch_button_stays_disabled_until_the_station_changes(monkeypatch, tmp_path):
    csv_path = make_csv(tmp_path / "466910.csv")
    monkeypatch.setattr(app.sources, "codis_download", lambda sid, progress=None: str(csv_path))
    monkeypatch.setattr(app.sources, "name_of", lambda sid: "鞍部")
    assert not app.fetch_button("busy")["interactive"] and "⏳" in app.fetch_button("busy")["value"]
    state, btn, _ = app.on_codis_fetch("466910", progress=lambda *a, **k: None)
    assert state["station"] == "466910" and not btn["interactive"]
    assert app.fetch_button()["interactive"] and app.on_source("codis")[3]["interactive"]
    state, btn, _ = app.on_codis_fetch("", progress=lambda *a, **k: None)
    assert state is None and btn["interactive"]


def test_prediction_time_is_limited_to_this_year_and_the_latest_published_hour():
    now = "2026-11-17 21:05"                       # 21:00 的觀測還沒上線，最晚只能預測 21:00
    day, hours, moved = app.target_choices(now=now)
    assert day == "2026-11-17" and not moved
    assert hours[0] == "00:00" and hours[-1] == "21:00" and "22:00" not in hours
    _, hours, moved = app.target_choices("2026-03-01", now=now)
    assert hours[0] == "00:00" and hours[-1] == "23:00" and len(hours) == 24 and not moved
    assert app.target_choices("2025-12-31", now=now)[:3:2] == ("2026-01-01", True)     # 去年 → 今年第一天
    assert app.target_choices("2026-11-20", now=now)[:3:2] == ("2026-11-17", True)     # 未來 → 最晚那天
    assert app.latest_target("2026-11-17 21:25") == app.pd.Timestamp("2026-11-17 22:00")
    day, hours, _ = app.target_choices(now="2026-12-31 23:30")    # 跨日：最晚可預測隔天 00 時
    assert day == "2027-01-01" and hours == ["00:00"]


def test_date_field_limits_and_echoes_the_clamped_day():
    html = app.date_input_html("2026-11-10", now="2026-11-17 21:05")
    assert 'min="2026-01-01"' in html and 'max="2026-11-17"' in html and 'value="2026-11-10"' in html
    box, day, hour = app.on_pred_day("2026-03-01", "23:00")
    assert day == "2026-03-01" and 'value="2026-03-01"' in box and hour["value"] == "23:00"
