# P2 日志查看器：tail 控制台拉起的 dsh web 落盘输出

- Status: implemented
- Date: 2026-08-29
- Related: docs/ROADMAP.md P2；core/dshctl.py start_dsh（数据源头）

## 背景

P2「日志查看器（tail+过滤+着色）」。调研结论：dsh 全家没有现成日志文件——
~/.dsh 无日志目录；dshmarket logEvent 只存内存（200 条随进程消亡）；用户自己终端
启动的 web 输出在宿主终端里。唯一落盘源是控制台 start_dsh 一直存在的重定向：
`%TEMP%/dsh-dash/dsh-web.{out,err}.log`（追加模式），此前没有任何界面能看到它。

## 关键决策

- **数据源即该落盘目录，边界明示**：只覆盖控制台拉起的实例；页面顶部提示自行启动的
  dsh 看不到。不做主日志区镜像落盘（二期候选），不接 dshmarket /dsh-market/logs 导出
  （依赖市场插件路由，脆弱）。
- **UI 线程 QTimer 轮询，不起后台线程**：纯本地小 IO（stat + 增量读，微秒级），
  services.py 信号桥约束的是"后台线程"，此处没有；页面每次进入重建，QTimer 挂 self
  随页面销毁。
- **字节级增量 tail（core/logs.Tailer）**：记 offset 只读新增；半行（写入方未写完 \n）
  留下次消费；截断/重建（size<offset）报 reset 由页面重新 bootstrap；二进制读 + 逐行
  decode(replace)，行级取 \r 兼容 CRLF。
- **read_tail 双防线**：最多回读 2MB + 最多 2000 行；字节窗口落在行中间时首行整行丢弃
  （首版用 readline 丢"对齐前残行"是错的——残行后半段会伪装成完整行，测试抓出后改为
  解析后 drop 首行，顺带解决多字节字符被截断的乱码）。
- **展示层脱敏**：out.log 含 web 登录 URL（token=...），显示时打码 token=***，文件不动。
- **着色**：复用主日志区配色（err #e07a7a / warn #e5c07b / ok #7ecb6a / 正文 #e6e6e6）；
  out 流按关键词分级（ELIFECYCLE failed/Exception→err，dsh web: http→ok），err 流整文件
  红色（它本身就是 stderr）。行首缩进以 &nbsp; 保留（HTML 折叠空白会毁掉堆栈缩进）。
- **过滤与缓冲**：包含/排除关键字大小写不敏感，作用于行缓冲渲染；行缓冲上限 5000 行，
  初始载入尾部 2000 行；缓冲是唯一事实源（切 tab/改过滤=全量单次 setHtml 重渲，
  增量走 appendHtml）。

## 放弃了什么

- QPlainTextEdit：maximumBlockCount 行数上限很香，但不支持 setHtml 全量重渲与
  appendHtml 混用的既有写法；主日志区是 QTextEdit，保持同一控件同一习惯。
- 后台线程 + 信号桥：为微秒级本地 IO 引入线程是过度设计。

## 验证

- 纯单元 335 例全绿（+19：路径/脱敏/分级/尾部读取含字节窗口与多字节边界/增量半行/
  截断重置/文件消失/过滤组合）。
- 离屏单页构造冒烟（不碰 MainWindow/3080）：真实日志 out 89 行 / err 88 行载入、
  轮询一轮、正常退出。
