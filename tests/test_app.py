from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StreamlitAppTests(unittest.TestCase):
    def test_diagnosis_interaction_has_no_exception(self) -> None:
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            self.skipTest("未安装可选网页依赖 streamlit")
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=20).run()
        self.assertEqual(0, len(app.exception))
        self.assertEqual("项目仿真数据", app.radio[0].value)
        self.assertEqual("开始诊断", app.button[0].label)
        warnings = [item.value for item in app.warning]
        self.assertTrue(any("仿真设备活动告警" in item for item in warnings))
        self.assertTrue(any("振动过高" in item for item in warnings))
        app.button[0].click().run()
        self.assertEqual(0, len(app.exception))
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual("草稿", metrics["结果状态"])
        self.assertEqual("必须", metrics["人工确认"])
        self.assertTrue(metrics["会话"])
        self.assertIn("工具成功率", metrics)
        self.assertIn("证据覆盖率", metrics)
        self.assertEqual(1, len(app.dataframe))
        feedback_radio = next(item for item in app.radio if item.label == "评价")
        self.assertEqual("说明（可选）", app.text_input[0].label)
        feedback_radio.set_value("部分有效")
        app.text_input[0].input("需要补充趋势")
        app.button[1].click().run()
        self.assertEqual(0, len(app.exception))
        self.assertTrue(any("反馈已记录" in item.value for item in app.success))
