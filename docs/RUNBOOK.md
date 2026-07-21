# 本地运行与恢复手册

## 适用范围

本手册面向教学和作品集环境。系统不连接、不控制真实工业设备；本地演示角色不等于企业身份认证。

## 启动前检查

1. 在项目根目录激活 `.venv`。
2. 运行 `python -m unittest discover -s tests`。
3. 运行 `python -m industrial_maintenance_agent.cli validate-knowledge`。
4. 上传数据前运行 `validate-telemetry-csv` 和 `validate-history-csv`。
5. 使用 `streamlit run app.py --server.port 8502` 启动网页。

## 运行边界

- 默认使用仿真数据；上传文件必须脱敏并带明确时区。
- `technician` 可诊断，`domain_expert` 可诊断和审核，`knowledge_admin` 只管理知识。
- 严重风险、无可靠知识、输出验证失败时不得绕过阻断。
- 趋势、盲测和延迟不是现场诊断结论或生产 SLA。

## 备份与校验

```powershell
python -m industrial_maintenance_agent.cli backup --output-dir backups
python -m industrial_maintenance_agent.cli verify-backup --manifest backups/<清单>.manifest.json
```

备份使用 SQLite 在线备份接口并生成 SHA-256 清单。`backups/` 不应提交公开仓库。

## 安全恢复演练

恢复只允许写入不存在的新文件，不覆盖正在使用的数据库：

```powershell
python -m industrial_maintenance_agent.cli restore-backup `
  --manifest backups/<清单>.manifest.json `
  --target data/runtime/recovery-check.db
```

恢复后用 `session --session-id <会话编号>` 核对数据。确认后先关闭应用并保留旧库，再由负责人决定是否切换；系统不会自动替换或删除现有数据库。

## 故障处理

- 网页无法打开：检查 8502 端口、虚拟环境和 Streamlit 日志。
- CSV 被拒绝：修复字段、时区、量程、重复点或设备身份漂移，不要关闭校验。
- 知识加载失败：运行 `validate-knowledge`，修复审核元数据、引用或可疑文本。
- 审计写入失败：本次结果不可作为已留痕会话；处理磁盘权限或空间后重新诊断。
- 备份校验失败：禁止恢复，保留文件并重新生成备份。

## 升级

升级前先备份，运行全量测试和盲测。真实身份源、CMMS/EAM、OT 数据或控制能力接入必须单独授权、安全评审并重新验收。
