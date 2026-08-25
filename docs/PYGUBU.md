# pygubu UI 定制说明

dsh-console-aio 主框架布局支持用 [pygubu-designer](https://github.com/alejandroautalan/pygubu-designer) 可视化编辑。

## 机制

- 布局文件: \`ui/main.ui\`（pygubu XML 格式）
- 运行时: 若安装了 pygubu 库 → 加载 \`ui/main.ui\` 构建主框架; 否则回退到内置代码布局
- 安装: \`pip install pygubu\`（可选, 不装不影响使用）

## 用 pygubu-designer 编辑

1. 安装 designer: \`pip install pygubu-designer\`，运行 \`pygubu-designer\`
2. 打开 \`ui/main.ui\`
3. 调整布局/样式/位置（拖拽组件、改属性）
4. 保存 → 重新启动 dsh-console-aio 即生效

## 重要约定（改动时请勿破坏）

以下组件 **id 固定**, 代码依赖它们绑定行为, 改名会导致程序异常:

| id | 作用 |
|----|------|
| topbar | 顶部栏容器 |
| title_lbl / ver_lbl / poll_lbl | 标题/版本/轮询信息 |
| deploy_combo | 部署选择下拉 |
| refresh_btn / config_btn / install_btn / env_btn | 顶部按钮 |
| body | 主体容器 |
| nav_list | 左侧导航 Listbox |
| center / page_host | 中栏容器与页面宿主 |
| right | 右状态栏容器(监控点代码生成) |
| logf / log_text / log_sb | 控制台输出区 |
| status_bar | 底部状态栏 |

- 可以改: 位置、大小、边距、颜色、字体、顺序
- 不要改: 组件 id、删除上述组件（页面容器 page_host 必须有）
- 右侧栏监控点(本机端口/隧道)由代码动态生成, 在 .ui 里只需保留 right 容器

## 打包注意

PyInstaller 打包时需包含 \`ui/main.ui\`（--add-data "ui/main.ui;ui"）与 pygubu 依赖。
