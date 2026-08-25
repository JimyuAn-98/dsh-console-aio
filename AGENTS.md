# AGENTS.md

dsh-console-aio — 零依赖 Windows GUI（Python stdlib tkinter），面向 dsh 用户的"控制台"：隧道管理、本机 dsh 启停/安装/更新、环境检查、健康监控，并逐步扩展 dsh 数据域管理（会话/工作区/插件/profile/用量统计等）。

## 项目定位

- **管理 + 监控 + 统计**，不做"使用"类功能：对话、任务、模型对比测试等留给 dsh web 本身。
- 目标用户是小白用户：界面中文、操作有确认、失败有明确中文提示。
- 预发布阶段（无外部消费者）：优先正确基础而非兼容 shim；重构可自由，但要同步更新所有引用。

## 仓库布局

dsh-console-aio.py   主程序（GUI + 隧道/监控/环境/安装 + 顶部"dsh 管理"菜单）
tunnel_mgr.py           纯 Python 隧道管理器（Tunnel 类: forward/reverse, start/persist/stop）
dsh_data.py             数据层（~/.dsh 各数据域读取/写入/备份，纯函数零依赖）
mgmt_*.py               管理窗口模块（会话/Agent模式/Profile/插件/任务看板/用量/LLM/主题/运维）
config.json             本地配置（真实 IP/用户名/路径，gitignore，绝不提交）
config.example.json     配置模板（全占位符）
启动dsh控制台.bat        双击启动器（conda pythonw 优先）
legacy/                 旧 .ps1（只读历史参考，界面不再调用）
docs/                   方案归档（ARCHITECTURE.md 架构 + PLANS.md 功能全景与路线）
.agents/notes/          Agent Note 决策记录（见 .agents/notes/README.md）

架构分层（详见 docs/ARCHITECTURE.md）：主程序只管导航与既有功能；数据层 dsh_data.py
（纯函数）与 UI 分离；每个管理窗口一个 mgmt_*.py，提供 Toplevel 子类，由主程序
_open_mgmt() 动态加载。新增管理窗口 = 新文件 + 在 _build_ui 的菜单注册一行。

## 命令

    python -m py_compile dsh-console-aio.py tunnel_mgr.py   # 编译检查（每次改动必跑）
    python dsh-console-aio.py                                # 运行 GUI
    git diff --cached --check                                   # 提交前检查（文件尾换行等）
    git push origin HEAD                                        # 推送（分支 main）

冒烟测试约定（只在本机无头环境做）：
- GUI 测试用 timeout -k 3 N python 包裹，防止 600s 挂起（真实 SSH 到不可达主机是挂起主因，测试勿触发）。
- 测试结束先 app.monitor_stop.set() 再 root.destroy()，避免 "main thread is not in main loop"。
- 版本/环境命令测试可用真实 mainloop（root.after(...); root.mainloop()）验证 after 回调。
- 不真跑 git clone / pnpm install / 升级命令；用 monkeypatch 拦截 _stream_cmd 验证命令参数与 env。

## 安全与密钥

- 真实值（服务器 IP、ssh 用户名、仓库路径）只存在 gitignore 的 config.json；DEFAULTS / README / docs / legacy / config.example.json 一律占位符（YOUR_PUBLIC_IP 等）。
- 历史已用 git-filter-repo 脱敏并 force push；任何新提交不得再引入真实 IP/用户名。
- 写 settings.yaml / cordis.yml / config.json 等用户配置前，先复制 .bak 备份；凭据类只做存在性提示，绝不读写密钥明文（dsh 的 apiKeyEnv 只引用环境变量名）。

## 约定（Conventions）

- 编码：源文件 UTF-8；子进程一律 text=True, errors="replace"（防 GBK UnicodeDecodeError 崩溃）。
- 子进程：Windows 批处理 shim 必须用 .cmd 后缀（pnpm.cmd / npm.cmd），否则 subprocess 找不到；一律 creationflags=CREATE_NO_WINDOW（防 pythonw 下弹黑窗）。
- 后台任务：工作线程 + self.root.after(0, ...) 回主线程更新 UI；窗口已销毁时 after 回调要 try/except tk.TclError。
- Tk 线程安全：只有主线程可操作 Tk 组件；工作线程只做 IO/子进程，结果经 after 回传。
- 三引号 docstring 禁令（本项目血泪教训）：经 JSON/补丁链路插入的多行字符串，三引号可能损坏成双引号导致 SyntaxError（invalid character '。'）。新代码一律用 # 注释代替 docstring；若必须用三引号，只写英文纯 ASCII 内容。
- 错误处理：空 except 必须注释说明吞了什么、为何其他异常到不了这里；不静默失败，失败要有中文日志（self.log(..., "err")）与状态提示。
- 危险操作：安装/更新/卸载/写配置一律先 messagebox.askyesno 确认"将执行什么"，用户点是才执行；命令流式输出到主日志区（复用 _stream_cmd）。
- 注释与文档：中文注释写契约与上下文，不叙述控制流，不注释代码中显而易见的事实；用直接具体的词，不用隐喻。
- 命令输出：长耗时命令用 _stream_cmd（Popen 流式读行 + 超时 deadline + kill 兜底），不 capture 完再弹窗。
- 文件结尾：恰好一个换行；git diff --cached --check 门禁。
- TODO 标记：FIXME(立即修) / TODO(计划) / XXX(危险)。
- 对称性：平行取值保持对称，不对称往往意味着漏提取。

## 防御模式

- 子进程：CREATE_NO_WINDOW + 超时 + kill；FileNotFoundError 单独捕获并提示（找不到 .cmd 时）。
- 监控线程：threading.Event 停止信号；循环里 event.wait(timeout) 代替裸 sleep。
- 路径拼接：一律 os.path.join / os.path.expanduser，不手拼字符串。
- 配置读取：load_config() 用 DEFAULTS 兜底合并，缺 key 不崩。

## 文档

- 功能/方案变更：同步更新 docs/PLANS.md（第 7 节功能全景 + 状态）与 RELEASE_NOTES.md；README 中英文同步。
- 关键决策（为什么 + 放弃了什么）：写 .agents/notes/{lifecycle}/{class}/yyyy-mm-dd-topic.md，格式见 .agents/notes/README.md。
- 已归档的 note 视为冻结：不编辑、不作为当前权威。

## 测试与质量

- 每次改动后：py_compile 必跑；GUI 相关改动做一次构造/打开窗口冒烟。
- 行为变更时：说明变更理由与影响面；测试描述行为而非"正确性"。
- 不默认跑全量测试；无 CI，质量靠提交前自查 + 上面约定。
