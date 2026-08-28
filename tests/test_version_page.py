# -*- coding: utf-8 -*-
# pages_version.py 纯逻辑函数测试。
# 覆盖: _cmp_ver 版本号比较。
# _fetch / _base_dir 等有副作用的函数只做参数验证, 不触发真实网络。

import os
import pytest


class TestCmpVer:
    """_cmp_ver: 版本号 x.y.z 比较, 返回 -1/0/1。"""

    def test_equal(self):
        from pyside.pages_version import _cmp_ver
        assert _cmp_ver("1.0.0", "1.0.0") == 0

    def test_less_than(self):
        from pyside.pages_version import _cmp_ver
        assert _cmp_ver("0.5.0", "1.0.0") == -1

    def test_greater_than(self):
        from pyside.pages_version import _cmp_ver
        assert _cmp_ver("2.0.0", "1.0.0") == 1

    def test_patch_difference(self):
        from pyside.pages_version import _cmp_ver
        assert _cmp_ver("1.0.1", "1.0.0") == 1
        assert _cmp_ver("1.0.0", "1.0.1") == -1

    def test_minor_difference(self):
        from pyside.pages_version import _cmp_ver
        assert _cmp_ver("1.2.0", "1.1.0") == 1

    def test_two_part_version(self):
        from pyside.pages_version import _cmp_ver
        assert _cmp_ver("1.0", "1.0") == 0
        assert _cmp_ver("1.1", "1.0") == 1

    def test_invalid_version_string(self):
        from pyside.pages_version import _cmp_ver
        # 非数字版本号应返回 0 (不崩溃)
        assert _cmp_ver("abc", "def") == 0

    def test_mixed_valid_invalid(self):
        from pyside.pages_version import _cmp_ver
        # "1.0.0" vs "abc" => (1,0,0) vs (0,) => greater
        assert _cmp_ver("1.0.0", "abc") == 1

    def test_empty_string(self):
        from pyside.pages_version import _cmp_ver
        assert _cmp_ver("", "") == 0

    def test_real_version(self):
        from pyside.pages_version import _cmp_ver
        assert _cmp_ver("0.5.0", "0.5.0") == 0


class TestResourceDir:
    """_resource_dir / _base_dir: 路径定位。"""

    def test_base_dir_not_frozen(self):
        from pyside.pages_version import _base_dir
        result = _base_dir()
        # 源码模式下应该是 pyside/ 的上级目录(项目根)
        assert os.path.isdir(result)

    def test_resource_dir_not_frozen(self):
        from pyside.pages_version import _resource_dir
        result = _resource_dir()
        assert os.path.isdir(result)
