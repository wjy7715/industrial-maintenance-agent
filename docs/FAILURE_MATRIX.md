# 失败模式矩阵

该矩阵用于本地发布门，不替代真实工厂的 HAZOP、FMEA、安全评审或现场验收。

| 失败模式 | 系统行为 | 自动化证据 | 剩余边界 |
|---|---|---|---|
| 未知设备或越权站点 | 在读取数据前停止，统一返回“未找到设备或无权访问” | `test_site_and_role_are_enforced_before_diagnosis` | 企业身份源尚未接入 |
| 遥测缺字段、越界或单位错误 | 失败关闭，不进入风险判断 | `UnitContractTests`、`TelemetryCsvRepositoryTests` | 真实传感器质量码未接入 |
| 时间戳无时区、重复或序列身份漂移 | 拒绝整个导入文件 | `test_naive_timestamp_and_inconsistent_scope_are_rejected` | 未处理实时流乱序重放 |
| 遥测陈旧或未来时间 | 保留数据但显式标记 stale/suspicious | `test_future_timestamp_is_marked_suspicious` | 阈值当前为演示配置 |
| 历史工具失败 | 保留失败轨迹并降级，不伪造历史 | `test_history_failure_degrades_without_fabricating_history` | 未实现网络重试 |
| 知识无匹配 | 返回空维修动作 | `test_no_match_does_not_invent_action` | 知识覆盖仍有限 |
| 知识缺引用、未双审或含注入文本 | 仓储加载前阻断发布包 | `AccessAndGovernanceTests` | 企业知识审批系统未接入 |
| 输出验证器拒绝或异常 | 状态 blocked，删除具体纠正动作 | `OutputValidatorTests` | 专家现场复核仍必需 |
| 严重风险 | 隐藏纠正动作并升级人工处理 | `test_high_risk_has_escalation_warning` | 真实阈值需现场批准 |
| 工具未注册或设备控制请求 | 默认拒绝；PLC 控制明确禁止 | `ToolContractTests` | 未来写适配器仍需逐项审批 |
| 审计写入失败 | 诊断结果显式标记不可作为已留痕会话 | `test_audit_permission_denial_is_visible_and_prevents_write` | 备份恢复在下一阶段完成 |
| 检索误匹配/漏匹配 | 独立盲测按假阳性、假阴性、错配分类 | `test_blind_set_has_negative_cases_and_performance_baseline` | 保留集规模小，不代表现场准确率 |

## 当前性能基线口径

- 命令：`python -m industrial_maintenance_agent.cli benchmark --repetitions 20`
- 测量对象：本机进程内 JSON 知识检索，不包含网络、模型、页面渲染和真实数据库延迟。
- 输出：盲测正确率、假阳性、假阴性、错配、P50、P95 和最大延迟。
- 禁止将该数字表述为生产 SLA；硬件、并发、数据量和部署方式变化后必须重新测量。
