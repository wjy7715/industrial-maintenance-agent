# 数据来源

## UCI AI4I 2020

- 官方页面：https://archive.ics.uci.edu/dataset/601/ai4i
- 许可证：CC BY 4.0
- 用途：公开预测性维护数据导入与质量校验。
- 限制：合成数据，不是本项目泵设备的真实遥测。

## 泵维修知识

1. Goulds Pump Installation, Operation and Maintenance Instructions
   https://www3.aps.anl.gov/APS_Engineering_Support_Division/Mechanical_Operations_and_Maintenance/Subsystems/ASD-ME-Group_files/data/RFWater/Maintenance/Pumps/GouldsPumpsO-M.pdf
2. U.S. Department of Energy Pump Systems
   https://www.energy.gov/cmei/ito/pump-systems
3. EPA Small Water Systems Manual
   https://nepis.epa.gov/Exe/ZyPURL.cgi?Dockey=940025K6.TXT

项目只保存必要的结构化释义、来源链接和位置，不在公开仓库重新分发完整厂商手册。

## 数据诚实性

- `data/sample` 是项目构造的仿真数据。
- `data/raw` 是可重新下载的公开数据，不提交 Git。
- 用户可临时上传脱敏 CSV 快照；系统只读解析，不保存原始上传文件，也不独立验证现场真实性。
- 维修知识与仿真遥测不是同一现场来源。
- 所有评测结论都限定在固定回归集，不能外推为工业准确率。

## 只读遥测 CSV 契约

必填字段：`equipment_id`、`equipment_type`、`captured_at`、`pressure_bar`、`vibration_mm_s`、`temperature_c`、`rotation_rpm`。可选字段：`equipment_model`、`active_errors`；多个告警用分号分隔。

适配器拒绝空文件、非 UTF-8、缺字段、重复设备、非有限数值、无效 ISO 8601 时间、超过 5 MB 或 10,000 行的数据。晚于系统时间超过 5 分钟的快照标为可疑，超过 24 小时的快照标为过期。

## 故障与维修闭环 CSV 契约

事件文件必填字段为 `event_id`、`equipment_id`、`event_type`、`event_at`。支持三类事件：

- `alarm_open`：必须提供 `error_code`。
- `alarm_close`：必须提供 `error_code`。
- `maintenance_closed`：必须提供 `action`、`result` 和带时区的 `verified_at`；`confirmed_cause` 可选。

事件编号必须唯一，所有时间必须是包含时区的 ISO 8601 时间，验证时间不得早于维修事件时间。适配器按时间顺序重放告警开闭状态，并把已完成维修作为证据；旧维修原因不会自动变成当前故障结论。
