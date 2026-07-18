---
name: industrial-maintenance
description: 使用项目内受约束的多工具流程查询仿真设备故障，并生成带来源的维修方案草稿。
---

# Industrial Maintenance

仅在用户要求查询本项目中的仿真工业设备、分析泵故障或生成维修方案草稿时使用。

## 执行方法

1. 确认用户提供设备编号和故障现象；示例设备为 `PUMP-001`、`PUMP-002`、`PUMP-003`。
2. 在项目根目录运行：

   `python -m industrial_maintenance_agent.cli diagnose --equipment-id <编号> --symptom "<现象>"`

3. 只整理命令返回的 JSON，不增加其中没有的原因、步骤或执行结果。
4. 必须保留 `draft`、`requires_human_confirmation`、安全警告、限制和来源。

## 禁止事项

- 不连接或控制真实设备。
- 不执行停机、拆卸、接线、维修或采购。
- 不把仿真数据描述为真实现场数据。
- 无匹配时不得自行补写维修措施。
