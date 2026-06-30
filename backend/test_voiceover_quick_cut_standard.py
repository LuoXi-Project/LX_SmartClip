import unittest

from app.core.auto_edit.voiceover_quick_cut import build_plan_from_clip_groups


def _single_clip_rows() -> list[dict]:
    return [
        {
            "id": "clip_a",
            "video_id": "video_1",
            "clip_path": "",
            "start_time": 0.0,
            "duration": 12.0,
            "asr_text": "",
            "asr_segments": (
                '[{"start":1.0,"end":2.0,"text":"第一句话。"},'
                '{"start":3.0,"end":5.0,"text":"第二句话。"}]'
            ),
        }
    ]


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

    def test_asr_fast_no_pad_keeps_exact_sentence_bounds(self) -> None:
        """默认 pad=0：asr_fast 严格按句子 start/end 裁剪。"""
        plan = build_plan_from_clip_groups(
            clip_groups=[_single_clip_rows()],
            strategy="asr_fast",
            video_title_hint="demo",
        )
        # 句子区间 1-2 与 3-5
        bounds = [(round(s.clip_start_offset_sec or 0.0, 3), round((s.clip_start_offset_sec or 0.0) + (s.override_duration_sec or 0.0), 3)) for s in plan.segments]
        self.assertIn((1.0, 2.0), bounds)
        self.assertIn((3.0, 5.0), bounds)

    def test_asr_fast_pad_extends_bounds_and_clamps_to_clip(self) -> None:
        """句头/句尾 pad 扩展裁剪区间，且约束在 [0, clip_dur]。"""
        plan = build_plan_from_clip_groups(
            clip_groups=[_single_clip_rows()],
            strategy="asr_fast",
            video_title_hint="demo",
            head_pad_sec=0.5,
            tail_pad_sec=0.7,
        )
        for s in plan.segments:
            st = s.clip_start_offset_sec or 0.0
            et = st + (s.override_duration_sec or 0.0)
            # 头补偿最多回到 0；尾补偿最多到 clip_dur(=12)
            self.assertGreaterEqual(st, 0.0 - 1e-6)
            self.assertLessEqual(et, 12.0 + 1e-6)
            # 句子原起点 1.0 → 应向前扩到 0.5（未越界）；原起点 3.0 → 2.5
            self.assertIn(round(st, 3), {0.5, 2.5})
            # 句子原终点 2.0 → 2.7；原终点 5.0 → 5.7
            self.assertIn(round(et, 3), {2.7, 5.7})

    def test_asr_fast_head_pad_clamps_at_zero(self) -> None:
        """句头 pad 大于句子起点时裁剪起点回退到 0（不越界）。"""
        plan = build_plan_from_clip_groups(
            clip_groups=[_single_clip_rows()],
            strategy="asr_fast",
            video_title_hint="demo",
            head_pad_sec=5.0,
            tail_pad_sec=0.0,
        )
        starts = [round(s.clip_start_offset_sec or 0.0, 3) for s in plan.segments]
        # 第一句起点 1.0，pad 5.0 → 0.0（越界回退）；第二句起点 3.0，pad 5.0 → 0.0
        for st in starts:
            self.assertEqual(st, 0.0)


if __name__ == "__main__":
    unittest.main()
