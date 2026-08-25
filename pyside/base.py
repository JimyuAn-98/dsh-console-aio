from PySide6.QtWidgets import QWidget


class BasePage(QWidget):
    # 所有 PySide6 页面的基类: 构造签名 (app)，app 即主窗口 MainWindow。
    # 子类实现 _build() 构建 UI; 通过 self.app 访问主窗口(loge/set_status/_current_deploy 等)。
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self._build()

    def _build(self):
        pass
