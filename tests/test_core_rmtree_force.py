# -*- coding: utf-8 -*-
# core/env.py _rmtree_force 删除加固 + 全程日志测试(纯单元, 不连网/不起子进程)。
# 覆盖: 只读文件+只读子目录可删净; log 回调收到开始/完成; 路径不存在时跳过并记日志。

import os
import stat

from core.env import _rmtree_force


class TestRmtreeForce:
    def test_removes_readonly_tree(self, tmp_path):
        root = tmp_path / 'repo'
        (root / '.git' / 'objects').mkdir(parents=True)
        f = root / '.git' / 'objects' / 'pack.idx'
        f.write_text('x', encoding='utf-8')
        os.chmod(str(f), stat.S_IREAD)
        os.chmod(str(root / '.git' / 'objects'), stat.S_IREAD | stat.S_IEXEC)
        _rmtree_force(str(root))
        assert not root.exists()

    def test_logs_start_and_done(self, tmp_path):
        d = tmp_path / 'gone'
        d.mkdir()
        lines = []
        _rmtree_force(str(d), log=lines.append)
        assert any('开始' in l for l in lines)
        assert any('完成' in l for l in lines)

    def test_missing_path_skips_with_log(self, tmp_path):
        lines = []
        _rmtree_force(str(tmp_path / 'nope'), log=lines.append)
        assert lines and '跳过' in lines[0]

    def test_deletes_junction_without_following(self, tmp_path):
        # junction 指向源目录本身(成环): 只删链接本身, 绝不递归进目标
        import subprocess
        if os.name != 'nt':
            import pytest
            pytest.skip('junction 仅 Windows')
        src = tmp_path / 'src'
        src.mkdir()
        (src / 'a.txt').write_text('x', encoding='utf-8')
        link = src / 'loop'
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(src)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            import pytest
            pytest.skip('无法创建 junction')
        assert os.path.isdir(str(link))
        _rmtree_force(str(src))
        assert not src.exists()
