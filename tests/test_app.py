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
        self.assertEqual("开始诊断", app.button[0].label)
        warnings = [item.value for item in app.warning]
        self.assertTrue(any("仿真设备活动告警" in item for item in warnings))
        self.assertTrue(any("振动过高" in item for item in warnings))
        app.button[0].click().run()
        self.assertEqual(0, len(app.exception))
        metrics = {item.label: item.value for item in app.metric}
        self.assertEqual("草稿", metrics["结果状态"])
        self.assertEqual("必须", metrics["人工确认"])
        self.assertEqual(1, len(app.dataframe))
