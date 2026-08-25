from PySide6.QtWidgets import QWidget


class BasePage(QWidget):
    # 所有 PySide6 页面的基类: 构造签名 (app)，app 即主窗口 MainWindow。
    # 子类实现 _build() 构建 UI; 通过 self.app 访问主窗口(loge/set_status/_current_deploy 等)。
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._build()

    def safe_emit(self, sig, *args):
        # 后台线程回调 UI 的安全发射: 页面切换销毁后, 对已删 QObject emit 会抛 RuntimeError,
        # 这里吞掉, 避免页面销毁竞态导致后台线程崩溃(AGENTS.md 线程收尾约定)。
        try:
            sig.emit(*args)
        except RuntimeError:
            pass

    def _build(self):
        pass
