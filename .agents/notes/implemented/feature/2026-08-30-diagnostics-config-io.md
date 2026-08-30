# 诊断报告 + 配置导出/导入（设置页「诊断与配置」标签）

- Status: implemented
- Date: 2026-08-30

## 背景

ROADMAP「下一步执行顺序」第 ② 步（P3 切入项）。目标用户是小白: 出问题时最需要的
是"一键拿到一份能直接外发的报告"; 换机/求助场景需要配置可带走可恢复。同批处理用户
两个插入话题: exe 图标"没变"(实为 Explorer 图标缓存) 与 代码签名诉求(零成本先上
SHA256SUMS)。

## 决策

1. **落位**: 不新增第 17 页, 设置页加第三个标签「诊断与配置」—— 诊断与配置本就是
   "排障/迁移"一族, 且延续弹窗收敛的页面化哲学。
2. **隐私红线优先**: 诊断只做本机只读操作(工具链 which+版本子进程 / tcp_ok 本机端口
   / 隧道 pid 存活), **不发起任何 SSH/远程连接**; ssh/lab 地址与用户名一律打码
   (mask_host: IPv4 保前两段/域名保首标签; mask_user: 留首字符), 仓库路径只取末级
   目录; 报告尾部显式标注"可安全外发"。tunnels_snapshot 刻意只取 pid/alive ——
   tunnel-pids.json 记录里有明文 host/user, 不入快照就不可能泄入报告。
3. **导出/导入 = 信封格式** (`_type`/`_version`/`_exported_at`/`config`): OTP
   deploy.xml 思想, 为未来 CLI 共享留口。导入只认信封(拒绝裸 dict, 防半截文件写盘),
   覆盖式写入(与导出对称), save_config 自动 .bak + reload_config 热重载, 写前
   QMessageBox 确认。
4. **线程范式**: 页面自有 daemon 线程 + 页面级 Signal + safe_emit(与设置页 SSH 测试
   同款, BUG-008 的教训落地); collect 契约兼容 service._run_result_op(首参 events),
   未来可无缝迁 service。
5. **签名的零成本缓解**: Release 资产新增 SHA256SUMS.txt(workflow 自动生成) ——
   不解决 SmartScreen 提示, 但解决"下载被篡改/认错文件"; 正式签名(年费/云服务)作为
   开放项留给用户拍板。

## 拒绝的替代方案

- **独立"诊断"导航页**: 内容量撑不起一页, 且设置页已有 tab 惯例。
- **诊断报告含完整 config 导出**: 报告面向外发, 必须默认脱敏; 完整配置走导出通道
  (用户自担保管责任), 两条通道语义分开。
- **导入做字段级合并**: 导入场景是迁移/回滚, 对称覆盖比"猜合并"可预期; 新增字段有
  derived() 兜底默认。
- **诊断走 service._run_result_op**: 现阶段页面自有线程更简单(同 SSH 测试范式),
  契约已兼容, 需要时再迁。

## 影响

- `core/diagnostics.py`(新), `core/config.py`(信封), `core/tunnel_mgr.py`
  (tunnels_snapshot), `ui/pages_settings.py`(Tab 3), `release.yml`(SHA256SUMS),
  `tests/test_diagnostics.py`(4 组), 文档三件套 + README。
- 353 例纯单元全过; 设置页三 tab 离屏冒烟 + 端到端报告生成验证。
- 顺手修复: tunnels_snapshot 首版假设 pid 记录为裸 int 的数据形状 bug(实测为 dict)。
