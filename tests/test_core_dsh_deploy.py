# -*- coding: utf-8 -*-
# core/dshctl.py 版本部署编排测试(零 Qt, 零真实 git/构建/进程)。
# 覆盖: dsh_repo_state / _default_branch / deploy_dsh_version(脏哨兵/校验失败/正常/allow_dirty)
# 与 update_dsh(to_main) 步骤编排。全部经 monkeypatch 拦截, 不跑任何真实命令。

import time

import core.dshctl as d


def _ctl(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    return d.DshCtl({"dash_repo": str(repo), "dash_port": 3080,
                     "dash_cmd": ["pnpm.cmd", "dsh", "web"]}), str(repo)


class _Rec:
    def __init__(self):
        self.steps = []

    def __call__(self, kind, payload):
        if kind == "step":
            self.steps.append(payload)


class TestDshRepoState:
    def test_missing_repo(self, tmp_path):
        assert d.dsh_repo_state({"dash_repo": ""})["exists"] is False
        assert d.dsh_repo_state({"dash_repo": str(tmp_path / "nope")})["exists"] is False

    def test_clean_branch_with_pin(self, tmp_path, monkeypatch):
        def fake(cmd, cwd, timeout=120):
            if cmd[1] == "rev-parse" and cmd[2] == "--abbrev-ref":
                return 0, "main", ""
            if cmd[1] == "rev-parse":
                return 0, "abc1234", ""
            return 0, "", ""

        monkeypatch.setattr(d, "_git_run", fake)
        st = d.dsh_repo_state({"dash_repo": str(tmp_path),
                               "dsh_version_pin": "dsh-v1.0.0"})
        assert st["exists"] is True and st["ref"] == "main"
        assert st["detached"] is False and st["dirty"] is False
        assert st["pin"] == "dsh-v1.0.0" and st["head"] == "abc1234"

    def test_detached_and_dirty(self, tmp_path, monkeypatch):
        def fake(cmd, cwd, timeout=120):
            if cmd[1] == "rev-parse" and cmd[2] == "--abbrev-ref":
                return 0, "HEAD", ""
            if cmd[1] == "status":
                return 0, " M x", ""
            return 0, "", ""

        monkeypatch.setattr(d, "_git_run", fake)
        st = d.dsh_repo_state({"dash_repo": str(tmp_path)})
        assert st["detached"] is True and st["dirty"] is True


class TestDefaultBranch:
    def test_from_origin_head(self, monkeypatch):
        monkeypatch.setattr(d, "_git_run", lambda *a, **k: (0, "origin/main", ""))
        assert d._default_branch("x") == "main"

    def test_fallback_main(self, monkeypatch):
        monkeypatch.setattr(d, "_git_run", lambda *a, **k: (1, "", "no head"))
        assert d._default_branch("x") == "main"


class TestDeployDshVersion:
    def _ready(self, tmp_path, monkeypatch, dirty=False, tag_ok=True):
        ctl, repo = _ctl(tmp_path)
        monkeypatch.setattr(time, "sleep", lambda s: None)

        def fake(cmd, cwd, timeout=120):
            if cmd[1] == "status":
                return (0, " M f", "") if dirty else (0, "", "")
            if cmd[1] == "rev-parse":
                return (0, "abc", "") if tag_ok else (128, "", "unknown revision")
            return 0, "", ""

        monkeypatch.setattr(d, "_git_run", fake)
        monkeypatch.setattr(ctl, "stop_dsh", lambda ev=None: True)
        monkeypatch.setattr(ctl, "start_dsh", lambda ev=None: True)
        monkeypatch.setattr(ctl, "stream_cmd", lambda *a, **k: True)
        pins = []
        monkeypatch.setattr(ctl, "_set_pin", lambda tag, ev=None: pins.append(tag))
        return ctl, repo, pins

    def test_dirty_returns_sentinel_without_side_effects(self, tmp_path, monkeypatch):
        ctl, repo, pins = self._ready(tmp_path, monkeypatch, dirty=True)
        rec = _Rec()
        r = ctl.deploy_dsh_version(rec, "dsh-v1.0.0")
        assert r["dirty"] is True and r["err"] == ""
        assert pins == [] and rec.steps == []

    def test_allow_dirty_bypasses_sentinel(self, tmp_path, monkeypatch):
        ctl, repo, pins = self._ready(tmp_path, monkeypatch, dirty=True)
        r = ctl.deploy_dsh_version(None, "dsh-v1.0.0", allow_dirty=True)
        assert r["err"] == "" and pins == ["dsh-v1.0.0"]

    def test_bad_tag(self, tmp_path, monkeypatch):
        ctl, repo, pins = self._ready(tmp_path, monkeypatch, tag_ok=False)
        r = ctl.deploy_dsh_version(None, "nope")
        assert r["dirty"] is False and r["err"].startswith("版本不存在")
        assert pins == []

    def test_empty_tag(self, tmp_path, monkeypatch):
        ctl, repo, pins = self._ready(tmp_path, monkeypatch)
        assert "tag 为空" in ctl.deploy_dsh_version(None, "  ")["err"]

    def test_happy_path_steps_and_pin(self, tmp_path, monkeypatch):
        ctl, repo, pins = self._ready(tmp_path, monkeypatch)
        rec = _Rec()
        r = ctl.deploy_dsh_version(rec, "dsh-v1.0.0")
        assert r["err"] == "" and r["dirty"] is False and r["tag"] == "dsh-v1.0.0"
        assert [s[0] for s in rec.steps] == list(range(1, 8))
        assert pins == ["dsh-v1.0.0"]


class TestUpdateDsh:
    def test_to_main_checks_out_default_branch(self, tmp_path, monkeypatch):
        ctl, repo = _ctl(tmp_path)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(d, "_default_branch", lambda r: "main")
        monkeypatch.setattr(ctl, "stop_dsh", lambda ev=None: True)
        monkeypatch.setattr(ctl, "start_dsh", lambda ev=None: True)
        monkeypatch.setattr(ctl, "_clear_pin", lambda ev=None: None)
        calls = []
        monkeypatch.setattr(ctl, "stream_cmd",
                            lambda cmd, **k: (calls.append(cmd), True)[1])
        rec = _Rec()
        assert ctl.update_dsh(rec, to_main=True) is True
        assert ["git", "checkout", "main"] in calls
        assert [s[0] for s in rec.steps] == list(range(1, 8))

    def test_missing_repo_returns_false(self, tmp_path, monkeypatch):
        ctl = d.DshCtl({"dash_repo": str(tmp_path / "nope")})
        assert ctl.update_dsh(None) is False
