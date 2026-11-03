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


def test_bad_upload_blocks_and_switching_source_clears_it(rain_root, tmp_path):
    make_station(rain_root, "467590")
    bad = app.on_upload(str(make_csv(tmp_path / "466930.csv", header=("時間", "雨量"))))
    cfg, err = app.make_config(*left(source="upload", upload=bad))
    assert err and skill.blocking(skill.field_errors(cfg, "", err))
    # 改回「已有資料的測站」：上傳的檔案被清掉，不會偷偷留著，也不會把上傳的站加進選單
    station_update, upload_update, state = app.on_source("existing")
    assert upload_update["value"] is None and state is None and station_update["visible"]
    cfg, err = app.make_config(*left(source="existing", upload=None))
    assert not err and cfg.station == "467590"


def test_upload_mode_never_uses_the_dropdown_station(rain_root, tmp_path):
    make_station(rain_root, "467590")
    good = app.on_upload(str(make_csv(tmp_path / "466930.csv")))
    cfg, err = app.make_config(*left(source="upload", upload=good, station="467590"))
    assert cfg.station == "466930" and not err
    cfg, err = app.make_config(*left(source="upload", upload=None, station="467590"))
    assert cfg.station == "" and err == "請上傳測站 CSV"
    assert "466930" not in [sid for _, sid in app.stations.station_choices()]


def test_upload_without_heavy_rain_blocks(rain_root, tmp_path):
    dry = app.on_upload(str(make_csv(tmp_path / "466930.csv", rain=(0, 1, 2))))
    _, err = app.make_config(*left(source="upload", upload=dry))
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
    assert "未經較佳化兩階段分類器對照" in stats and "守門" not in stats and "第 1 代 / 純 MAE" not in stats
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
    assert not out[12].startswith("---") and "name: rain-autoresearch" not in out[12]
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
