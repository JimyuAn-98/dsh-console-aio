# 实施方案与计划: dsh 0.1.2+ 跨机器 Token 自动同步与免密链接复制 (v1)

> 状态: ✅ 已完成全部实施与验证
> 日期: 2026-09-02
> 责任: Antigravity

---

## 一、背景与目标

`deepseek harness` 0.1.2+ 引入了随机 32 字节一次性启动 Token 鉴权（`http://127.0.0.1:PORT/?token=...`）。本机启动 dsh 时官方程序已自带自动打开浏览器，因此**控制台不做任何“打开 Web 界面”的多余按钮**。

本方案仅聚焦于解决**“家”访问“办公室/实验室”的跨机器 401 鉴权痛点**：

1. **静默捕获与推送（办公室 / 实验室节点）**：
   - 启动 dsh 时后台静默提取 stdout 中的 Token；
   - 建立反向 SSH 隧道时，顺带通过已有 SSH 执行一条轻量指令写入公网 VPS 的 `~/.dsh_runtime/<node>.token`（权限 `600`，零公网外部服务依赖）。
2. **信箱读取与链接复制（家 / 客户端节点）**：
   - 家里控制台打通远程端口后，通过 SSH 读取公网信箱的 Token；
   - 在远程部署卡片上提供 **「复制免密链接」** 按钮（如 `http://127.0.0.1:8091/?token=xxxx`），方便用户在家里浏览器初次打开换取 30 天 Cookie。

---

## 二、架构与数据流图

```
【办公室 / 实验室】(部署 dsh)
  dsh web 启动 ──► stdout 静默捕获 Token ──► SSH 反向隧道建立时写入 VPS:~/.dsh_runtime/<node>.token (chmod 600)
                                                                            │
                                                                   (仅作为安全信箱文件)
                                                                            ▼
【家】(客户端控制台)
  拉取 SSH 隧道 ──► SSH 读取 VPS 信箱 Token ──► 远程卡片提供「复制免密链接」(http://127.0.0.1:8091/?token=...)
                                                                            │
                                                                   (初次复制到浏览器打开)
                                                                            ▼
                                                               浏览器自动换取 30 天 Cookie
                                                               (后续 30 天直接访问免输入)
```

---

## 三、拟实施改动清单

### 1. 业务核心层（`core/`，纯 Python 零 Qt）

- **`core/dshctl.py`**：
  - 新增 `extract_auth_token(line: str) -> Optional[str]`：从 stdout 输出中正则提取 32 字节 Token；
  - 新增 `save_runtime_token(node_name: str, token: str)` 与 `load_runtime_token(node_name: str) -> Optional[str]`：本地运行时状态管理；
  - 在 `DshCtl.start_dsh` 流式执行日志中接入 Token 静默捕获。
- **`core/tunnels.py` / `core/tunnel_mgr.py`**：
  - 新增 `push_node_token(ssh_cfg, node_name, token) -> bool`：建立反向隧道时通过 SSH 执行 `mkdir -p ~/.dsh_runtime && echo '<token>' > ~/.dsh_runtime/<node_name>.token && chmod 600 ~/.dsh_runtime/<node_name>.token`；
  - 新增 `pull_node_token(ssh_cfg, node_name) -> Optional[str]`：通过 SSH 执行 `cat ~/.dsh_runtime/<node_name>.token 2>/dev/null`。

### 2. 信号桥与服务层（`app/`）

- **`app/services.py`**：
  - 在 `start_dsh` 捕获到 Token 后，记录本地状态并在建立反向隧道时调用 `push_node_token`；
  - 在 `read_overview`（或部署探测）读取远程部署状态时，自动带出远程节点的 Token，组装 `auth_url` 放入节点数据中。

### 3. 前端界面层（`ui/`）

- **`ui/pages_overview.py` / `ui/pages_deployments.py`**：
  - 在总览页的**远程部署卡片**（非本机）或部署管理页的远程节点上，增加轻量的 **「复制免密链接」** 按钮；
  - 用户点击后复制 `http://127.0.0.1:<LOCAL_PORT>/?token=<TOKEN>` 到剪贴板，并在状态栏提示“已复制远程免密链接”。
  - **不添加任何“打开 Web 界面”按钮**。

---

## 四、验证计划

1. 语法与编译检查：`python -m compileall -q dsh-console-aio.py core ui app tests`；
2. 纯单元测试：`pytest tests/ -q`；
3. GUI 冒烟测试：`pytest tests/ -m gui -q`；
4. 验证整个 UI 无任何冗余的打开浏览器逻辑。
