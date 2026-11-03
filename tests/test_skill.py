from rainui import skill
from rainui.skill import RunConfig


def cfg(**kw):
    base = dict(station="466930", run_name="竹子湖 第一次", model="deepseek/deepseek-v4.1-flash-1017")
    base.update(kw)
    return RunConfig(**base)


def test_default_goal_has_no_override():
    text = skill.render(cfg())
    assert "介面覆寫" not in text
    assert "`mae_ge40mm`" in text and "under" in text and "rmse" in text


def test_changed_goal_writes_highest_priority_override_before_rules():
    text = skill.render(cfg(metric="rmse", threshold=30))
    assert "## 介面覆寫（優先級最高）" in text
    assert text.index("介面覆寫") < text.index("## 0. 必讀")
    assert "`rmse_ge30mm`" in text and "budget_guard.py" in text and "tests/test_budget_guard.py" in text


def test_subset_of_subgoals_and_semantic_mode_are_overrides():
    assert not skill.is_default_goal(cfg(subgoals=["under"]))
    assert not skill.is_default_goal(cfg(sub_mode="semantic", sub_text="大雨寧可高估"))
    assert "大雨寧可高估" in skill.render(cfg(sub_mode="semantic", sub_text="大雨寧可高估"))


def test_goal_key_names():
    assert skill.goal_key(cfg()) == "mae_ge40mm"
    assert skill.goal_key(cfg(metric="under", threshold=25.5)) == "count_under_ge25.5mm"


def test_fingerprint_ignores_model_name_and_parallel_but_not_goals():
    a = skill.fingerprint(cfg())
    assert a == skill.fingerprint(cfg(model="openai/gpt-5", run_name="別的名字", parallel=1))
    assert a != skill.fingerprint(cfg(threshold=30))
    assert a != skill.fingerprint(cfg(station="467590"))
    assert a != skill.fingerprint(cfg(template=skill.DEFAULT_TEMPLATE + "\n多一行"))


def test_field_errors_block_bad_inputs():
    assert not skill.blocking(skill.field_errors(cfg(), ""))
    assert skill.field_errors(cfg(), "abc")["key"][0] == "err"
    assert not skill.field_errors(cfg(), "sk-or-v1-" + "a" * 32)
    assert "sub" in skill.field_errors(cfg(subgoals=[]), "")
    assert "evo" in skill.field_errors(cfg(max_gen=1), "")
    assert "tpl" in skill.field_errors(cfg(template="沒有欄位"), "")
    assert skill.field_errors(cfg(), "", source_error="找不到欄位：降水量(mm)")["file"][1].startswith("找不到欄位")


def test_skill_file_and_command_never_show_the_key():
    c = cfg()
    md = skill.skill_markdown(c)
    assert md.startswith("---\nname: rain-autoresearch-466930")
    args = skill.hermes_args(c, "D:/root", "prompt.txt", api_key="sk-or-v1-secret")
    assert args[args.index("-m") + 1] == "deepseek/deepseek-v4.1-flash-1017"
    assert "sk-or-v1-secret" not in skill.shell_preview(c, "D:/root")
