# -*- coding: utf-8 -*-
# ui/cacheable.py - 数据页通用缓存编排 mixin。
# 存储层在 core/cache.py(kind -> {fetched_at, data}); 本模块把"读缓存 / 比数据源 mtime /
# 后台拉取 / 写缓存 / RefreshIndicator 指示灯 / busy 防重入"这段每页重复的编排收口一处。
# 页面实现 4 个必需钩子, 按需覆盖可选钩子; 不 import Qt, 便于用假页面做纯单元测试。
# 约定: 页面须有 self._busy、self._spinner(RefreshIndicator) 与 self.app.service。

from core import cache as core_cache


class CacheableMixin:
    # ── 必需钩子 ──
    def _cache_kind(self):
        raise NotImplementedError

    def _cache_src_mtime(self):
        raise NotImplementedError

    def _cache_fetch(self):
        # 发起后台读取(service.xxx); 回包交 _cache_result 收口。
        raise NotImplementedError

    def _cache_apply(self, data, err=""):
        # 渲染: data 为缓存/新数据; err 非空时为错误态(此时 data 为 _cache_empty_data())。
        raise NotImplementedError

    # ── 可选钩子(默认实现足够通用) ──
    def _cache_begin(self):
        # 未命中缓存、即将后台拉取时(设 _pending / 禁按钮 / 状态文案)。
        pass

    def _cache_end(self):
        # 回包收口时(清 _pending / 恢复按钮)。
        pass

    def _cache_empty_data(self):
        # 错误态交给 _cache_apply 的数据(如 []/{}); 默认 None。
        return None

    def _cache_valid(self, data):
        # 数据形状校验; 默认非 None。
        return data is not None

    def _cache_error_text(self, data, err):
        # 错误文案; 默认取 err, 缺省"读取失败"。页面可覆盖以带上数据里的 error 字段。
        return str(err or "读取失败")

    def _cache_hit_extra(self, data):
        # 命中缓存后的补充动作(如补实时探活); 默认无。
        pass

    def _cache_mark_changed(self, changed):
        # 指示灯收尾; 页面可覆盖以同步自己的状态文字。
        sp = getattr(self, "_spinner", None)
        if sp is None:
            return
        if changed:
            sp.set_status("warn")
            sp.setToolTip("数据有变化(已刷新)")
        else:
            sp.set_status("ok")
            sp.setToolTip("无变化(缓存已是最新)")

    # ── 编排 ──
    # 页面可直接调用 refresh()/ _refresh(); 二者都是同一入口(兼容既有命名)。
    def refresh(self, force=False):
        self._cache_refresh(force)

    def _refresh(self, force=False):
        self._cache_refresh(force)

    def _cache_refresh(self, force=False):
        if getattr(self, "_busy", False):
            # force 只用于"绕过缓存", 不绕过"正在读取中"的防重入
            return
        kind = self._cache_kind()
        data, _ = core_cache.read_cache(kind)
        if (not force and data is not None
                and not core_cache.needs_refresh(kind, self._cache_src_mtime())):
            # 缓存命中: 直接呈现 + 绿; 页面可补实时动作
            self._cache_apply(data, "")
            sp = getattr(self, "_spinner", None)
            if sp is not None:
                sp.set_status("ok")
                sp.setToolTip("无变化(缓存已是最新)")
            self._cache_hit_extra(data)
            return
        self._busy = True
        self._cache_begin()
        sp = getattr(self, "_spinner", None)
        if sp is not None:
            sp.set_loading(True)
        self._cache_fetch()

    def _cache_result(self, data, err=""):
        # service 回包统一收口: 解 busy -> 校验 -> 写缓存 -> 渲染 -> 指示灯
        self._busy = False
        self._cache_end()
        sp = getattr(self, "_spinner", None)
        if sp is not None:
            sp.set_loading(False)
        if err or not self._cache_valid(data):
            self._cache_apply(self._cache_empty_data(),
                              self._cache_error_text(data, err))
            if sp is not None:
                sp.set_status("err")
                sp.setToolTip("数据获取错误: " + str(err or ""))
            return False
        changed = core_cache.data_changed(self._cache_kind(), data)
        core_cache.write_cache(self._cache_kind(), data)
        self._cache_apply(data, "")
        self._cache_mark_changed(changed)
        return True
