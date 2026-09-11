# -*- coding: utf-8 -*-
# core/pkgmgr.py 纯逻辑测试(不跑真实 pnpm 安装/更新): 环境修正 / 模式判定 / 命令拼装。

import json
import os

import core.pkgmgr as pkgmgr


class TestPnpmEnv:
    def test_prepends_bin_and_never_sets_pnpm_home(self, monkeypatch):
        # BUG-013 回归: 不能把 PNPM_HOME 设成 bin 目录本身, 否则 pnpm 会拼出 <...>\bin\bin
        monkeypatch.delenv('PNPM_HOME', raising=False)
        monkeypatch.setenv('LOCALAPPDATA', 'C:/Users/x/AppData/Local')
        monkeypatch.setenv('PATH', 'C:/Windows')
        env = pkgmgr.pnpm_env()
        binp = os.path.join('C:/Users/x/AppData/Local', 'pnpm', 'bin')
        assert env['PATH'].split(os.pathsep)[0] == binp
        assert 'PNPM_HOME' not in env

    def test_bin_dir_is_under_pnpm_home(self, monkeypatch):
        # 已有 PNPM_HOME 时: 全局 bin 目录 = <PNPM_HOME>\bin, 且保留原 PNPM_HOME 不覆盖
        monkeypatch.setenv('PNPM_HOME', 'C:/pnpm-home')
        monkeypatch.setenv('PATH', 'C:/Windows')
        env = pkgmgr.pnpm_env()
        assert env['PATH'].split(os.pathsep)[0] == os.path.join('C:/pnpm-home', 'bin')
        assert env['PNPM_HOME'] == 'C:/pnpm-home'

    def test_no_duplicate(self, monkeypatch):
        binp = os.path.join('C:/Users/x/AppData/Local', 'pnpm', 'bin')
        monkeypatch.delenv('PNPM_HOME', raising=False)
        monkeypatch.setenv('LOCALAPPDATA', 'C:/Users/x/AppData/Local')
        monkeypatch.setenv('PATH', binp)
        assert pkgmgr.pnpm_env()['PATH'] == binp


class TestSourceInfo:
    def _repo(self, tmp_path, name, version='1.2.3', apps_cli=False):
        repo = tmp_path / 'repo'
        repo.mkdir(exist_ok=True)
        (repo / 'package.json').write_text(
            json.dumps({'name': name, 'version': version}), encoding='utf-8')
        if apps_cli:
            (repo / 'apps' / 'cli').mkdir(parents=True)
        return repo

    def test_dsh_root_is_source(self, tmp_path):
        info = pkgmgr.source_info(str(self._repo(tmp_path, '@deepseek-ai/dsh-root', '0.1.5-rc.2')))
        assert info['ok'] is True and info['version'] == '0.1.5-rc.2'

    def test_apps_cli_counts(self, tmp_path):
        assert pkgmgr.source_info(str(self._repo(tmp_path, 'whatever', apps_cli=True)))['ok'] is True

    def test_other_repo_not_source(self, tmp_path):
        assert pkgmgr.source_info(str(self._repo(tmp_path, 'some-other')))['ok'] is False

    def test_missing(self, tmp_path):
        assert pkgmgr.source_info(str(tmp_path / 'nope'))['ok'] is False
        assert pkgmgr.source_info('')['ok'] is False


class TestDetectMode:
    def _stub(self, monkeypatch, ok, version='9', error=''):
        monkeypatch.setattr(pkgmgr, 'package_info',
                            lambda force=False: {'ok': ok, 'version': version, 'error': error})
        monkeypatch.setattr(pkgmgr, 'global_bin_dir', lambda: 'B')

    def test_explicit_wins(self, monkeypatch):
        self._stub(monkeypatch, False)
        info = pkgmgr.detect_mode({'dash_repo': '', 'dsh_install_mode': 'package'})
        assert info['mode'] == 'package' and info['explicit'] == 'package'

    def test_source_preferred_over_package(self, tmp_path, monkeypatch):
        repo = tmp_path / 'r'
        repo.mkdir()
        (repo / 'package.json').write_text(
            json.dumps({'name': '@deepseek-ai/dsh-root', 'version': '1'}), encoding='utf-8')
        self._stub(monkeypatch, True)
        assert pkgmgr.detect_mode({'dash_repo': str(repo)})['mode'] == 'source'

    def test_package_when_no_source(self, monkeypatch):
        self._stub(monkeypatch, True)
        assert pkgmgr.detect_mode({'dash_repo': ''})['mode'] == 'package'

    def test_none_keeps_probe_error(self, monkeypatch):
        self._stub(monkeypatch, False, error='boom')
        info = pkgmgr.detect_mode({'dash_repo': ''})
        assert info['mode'] == 'none' and info['package']['error'] == 'boom'


class TestCommands:
    def test_npm_version_normalization(self):
        # dsh Release tag 带 dsh- 前缀; 包模式必须映射成 npm 版本
        assert pkgmgr.npm_version('dsh-v0.1.5-rc.2') == '0.1.5-rc.2'
        assert pkgmgr.npm_version('v0.1.5-rc.1') == '0.1.5-rc.1'
        assert pkgmgr.npm_version('@0.1.5') == '0.1.5'
        assert pkgmgr.npm_version('0.1.5') == '0.1.5'
        assert pkgmgr.npm_version('') == ''

    def test_install_cmd_strips_prefix(self):
        assert pkgmgr.install_cmd('dsh-v0.1.5-rc.2')[-1] == '@deepseek-ai/dsh@0.1.5-rc.2'
        assert pkgmgr.install_cmd('v0.1.5-rc.1')[-1] == '@deepseek-ai/dsh@0.1.5-rc.1'
        assert pkgmgr.install_cmd('')[-1] == '@deepseek-ai/dsh'

    def test_update_remove_cmd(self):
        assert pkgmgr.update_cmd()[1:3] == ['update', '-g']
        assert pkgmgr.remove_cmd()[1:3] == ['remove', '-g']



class TestPackageModeLifecycle:
    # 包模式路由: update / deploy / uninstall 必须走 pnpm -g 命令(不碰 git)。
    def _ctl(self, monkeypatch):
        import core.dshctl as dshctl
        calls = []
        ctl = dshctl.DshCtl({'dash_port': 3080, 'dash_repo': '', 'dash_cmd': [],
                             'update_timeout': 30})
        monkeypatch.setattr(pkgmgr, 'detect_mode',
                            lambda cfg=None, force=False: {'mode': 'package'})
        monkeypatch.setattr(pkgmgr, 'package_info',
                            lambda force=False: {'ok': True, 'version': '9', 'error': ''})
        monkeypatch.setattr(ctl, 'stop_dsh', lambda events=None: calls.append(['stop']) or True)
        monkeypatch.setattr(ctl, 'start_dsh', lambda events=None: calls.append(['start']) or True)
        monkeypatch.setattr(ctl, 'stream_cmd',
                            lambda cmd, cwd=None, env=None, events=None, timeout_override=None:
                            calls.append(list(cmd)) or True)
        return ctl, calls

    def test_update_routes_to_pnpm(self, monkeypatch):
        ctl, calls = self._ctl(monkeypatch)
        assert ctl.update_dsh(None) is True
        assert ['stop'] in calls and ['start'] in calls
        assert pkgmgr.update_cmd() in calls

    def test_deploy_version_strips_v(self, monkeypatch):
        ctl, calls = self._ctl(monkeypatch)
        r = ctl.deploy_dsh_version(None, tag='v0.1.5-rc.1')
        assert r['err'] == '' and r['tag'] == 'v0.1.5-rc.1'
        assert pkgmgr.install_cmd('0.1.5-rc.1') in calls

    def test_deploy_version_strips_dsh_v(self, monkeypatch):
        # 真实 dsh Release tag 形如 dsh-v0.1.5-rc.2 -> npm 0.1.5-rc.2
        ctl, calls = self._ctl(monkeypatch)
        r = ctl.deploy_dsh_version(None, tag='dsh-v0.1.5-rc.2')
        assert r['err'] == '' and r['tag'] == 'dsh-v0.1.5-rc.2'
        assert ['pnpm.cmd', 'add', '-g', '@deepseek-ai/dsh@0.1.5-rc.2'] in calls

    def test_uninstall_routes_to_pnpm_remove(self, monkeypatch):
        import core.dshctl as dshctl
        import core.env as env_mod
        import core.config as dsh_config
        calls = []
        monkeypatch.setattr(pkgmgr, 'detect_mode',
                            lambda cfg=None, force=False: {'mode': 'package'})
        monkeypatch.setattr(pkgmgr, 'package_info',
                            lambda force=False: {'ok': False, 'version': '', 'error': ''})
        monkeypatch.setattr(dsh_config, 'load_config', lambda path=None: {})
        monkeypatch.setattr(dsh_config, 'load_derived',
                            lambda path=None: {'dash_port': 3080, 'update_timeout': 30})
        def fake_stream(self, cmd, cwd=None, env=None, events=None, timeout_override=None):
            calls.append(list(cmd))
            return True
        monkeypatch.setattr(dshctl.DshCtl, 'stream_cmd', fake_stream)
        monkeypatch.setattr(dshctl.DshCtl, 'stop_dsh', lambda self, events=None: True)
        r = env_mod.uninstall_dsh(None, keep_data=True)
        assert r['err'] == '' and pkgmgr.remove_cmd() in calls
