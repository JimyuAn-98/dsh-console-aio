# -*- coding: utf-8 -*-
# dsh_core/version.py 纯逻辑函数测试(业务已从 pages_version.py 下沉到 core)。
# 覆盖: cmp_ver 版本号比较。
# fetch / program_dir 等有副作用的函数只做路径验证, 不触发真实网络。

import os

from dsh_core.version import cmp_ver, program_dir, resource_dir


class TestCmpVer:
    # cmp_ver: 版本号 x.y.z 比较, 返回 -1/0/1。
    def test_equal(self):
        assert cmp_ver("1.0.0", "1.0.0") == 0

    def test_less_than(self):
        assert cmp_ver("0.5.0", "1.0.0") == -1

    def test_greater_than(self):
        assert cmp_ver("2.0.0", "1.0.0") == 1

    def test_patch_difference(self):
        assert cmp_ver("1.0.1", "1.0.0") == 1
        assert cmp_ver("1.0.0", "1.0.1") == -1

    def test_minor_difference(self):
        assert cmp_ver("1.2.0", "1.1.0") == 1

    def test_two_part_version(self):
        assert cmp_ver("1.0", "1.0") == 0
        assert cmp_ver("1.1", "1.0") == 1

    def test_invalid_version_string(self):
        # 非数字版本号应返回 0 (不崩溃)
        assert cmp_ver("abc", "def") == 0

    def test_mixed_valid_invalid(self):
        # "1.0.0" vs "abc" => (1,0,0) vs (0,) => greater
        assert cmp_ver("1.0.0", "abc") == 1

    def test_empty_string(self):
        assert cmp_ver("", "") == 0

    def test_real_version(self):
        assert cmp_ver("0.5.0", "0.5.0") == 0


class TestResourceDir:
    # program_dir / resource_dir: 路径定位。
    def test_program_dir_not_frozen(self):
        result = program_dir()
        # 源码模式下应该是 dsh_core/ 的上级目录(项目根)
        assert os.path.isdir(result)

    def test_resource_dir_not_frozen(self):
        result = resource_dir()
        assert os.path.isdir(result)
