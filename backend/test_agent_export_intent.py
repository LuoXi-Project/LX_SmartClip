import unittest

from app.agent.export_intent import detect_export_intent


class ExportIntentTests(unittest.TestCase):
    def test_realize_phrases(self) -> None:
        for msg in (
            "导出成片",
            "导出成片（保留原声）",
            "导出成片（配音版）",
            "按当前方案成片",
            "生成成片",
            "开始导出成片",
        ):
            intent = detect_export_intent(msg)
            self.assertIsNotNone(intent, msg)
            self.assertIn(intent.kind, ("realize", "tts_realize"))

    def test_jianying(self) -> None:
        intent = detect_export_intent("导出剪映草稿")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.kind, "jianying")

    def test_tts(self) -> None:
        intent = detect_export_intent("不保留原声，进行tts配音")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.kind, "tts_realize")
        self.assertTrue(intent.force_tts_pipeline)

    def test_long_chat_not_matched(self) -> None:
        self.assertIsNone(
            detect_export_intent("帮我用素材库最新视频做一个60秒电商口播并导出成片放到网盘")
        )


if __name__ == "__main__":
    unittest.main()
