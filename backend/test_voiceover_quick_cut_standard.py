import unittest

from app.core.auto_edit.voiceover_quick_cut import build_plan_from_clip_groups


class VoiceoverQuickCutStandardTests(unittest.TestCase):
    def test_standard_quick_cut_filters_filler_and_keeps_value_sentences(self) -> None:
        rows = [
            {
                "id": "clip_a",
                "video_id": "video_1",
                "clip_path": "",
                "start_time": 0.0,
                "duration": 12.0,
                "asr_text": "",
                "asr_segments": (
                    '[{"start":0.0,"end":1.0,"text":"嗯啊这个"},'
                    '{"start":1.2,"end":4.0,"text":"这个产品的核心优势是续航很久。"},'
                    '{"start":4.5,"end":7.5,"text":"然后就是怎么说呢"},'
                    '{"start":8.0,"end":11.5,"text":"价格优惠也比较明显，推荐预算有限的人。"}]'
                ),
            }
        ]

        plan = build_plan_from_clip_groups(
            clip_groups=[rows],
            strategy="standard",
            video_title_hint="demo",
            target_duration_sec=6.0,
        )

        text = "\n".join(seg.subtitle.text for seg in plan.segments)
        self.assertIn("核心优势", text)
        self.assertIn("价格优惠", text)
        self.assertNotIn("嗯啊这个", text)
        self.assertNotIn("怎么说呢", text)
        self.assertEqual(plan.title, "口播快剪（标准）· demo")


if __name__ == "__main__":
    unittest.main()
