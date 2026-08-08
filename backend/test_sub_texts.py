"""sub_texts 工具单测：验证 3 子空间文本拼装与边界。"""
import json
import unittest

from app.core.vector_db.sub_texts import (
    WRITABLE_SUBSPACES,
    build_sub_texts,
    build_legacy_text,
    non_empty_subspaces,
)


class TestBuildSubTexts(unittest.TestCase):
    def test_full_split(self):
        out = build_sub_texts(
            asr_text="我走了",
            vlm_description="男人摔门离开",
            abstract_summary="离别与抉择",
            keywords=["摔门", "离开"],
            emotion_tags=["悲伤", "决绝"],
        )
        self.assertEqual(out["asr"], "我走了 摔门 离开")
        self.assertEqual(out["vlm"], "男人摔门离开")
        self.assertEqual(out["abstract"], "离别与抉择 悲伤 决绝")

    def test_keywords_as_json_string(self):
        # DB 里 keywords 存的是 JSON 字符串
        out = build_sub_texts(
            asr_text="台词",
            keywords=json.dumps(["a", "b"], ensure_ascii=False),
        )
        self.assertEqual(out["asr"], "台词 a b")

    def test_empty_fields_produce_empty_subspace(self):
        out = build_sub_texts(asr_text="只有台词")
        self.assertEqual(out["asr"], "只有台词")
        self.assertEqual(out["vlm"], "")
        self.assertEqual(out["abstract"], "")

    def test_all_empty(self):
        out = build_sub_texts()
        self.assertEqual(out, {"asr": "", "vlm": "", "abstract": ""})

    def test_whitespace_cleaned(self):
        out = build_sub_texts(asr_text="  带空格  ", vlm_description=None)
        self.assertEqual(out["asr"], "带空格")
        self.assertEqual(out["vlm"], "")

    def test_emotion_into_abstract(self):
        out = build_sub_texts(abstract_summary="主题", emotion_tags=["紧张"])
        self.assertEqual(out["abstract"], "主题 紧张")

    def test_none_keywords_emotion(self):
        out = build_sub_texts(keywords=None, emotion_tags=None)
        self.assertEqual(out["asr"], "")
        self.assertEqual(out["abstract"], "")


class TestNonEmptySubspaces(unittest.TestCase):
    def test_filters_empty(self):
        subs = build_sub_texts(asr_text="台词", abstract_summary="主题")
        self.assertEqual(non_empty_subspaces(subs), ["asr", "abstract"])

    def test_all_empty_returns_none(self):
        subs = build_sub_texts()
        self.assertEqual(non_empty_subspaces(subs), [])

    def test_order_stable(self):
        subs = {"vlm": "x", "asr": "y", "abstract": ""}
        # 遵循 WRITABLE_SUBSPACES 顺序
        self.assertEqual(non_empty_subspaces(subs), ["asr", "vlm"])
        self.assertEqual(WRITABLE_SUBSPACES, ("asr", "vlm", "abstract"))


class TestLegacyText(unittest.TestCase):
    def test_legacy_concatenates_all(self):
        legacy = build_legacy_text(
            asr_text="台词",
            vlm_description="画面",
            abstract_summary="摘要",
            keywords=["kw1"],
            emotion_tags=["e1"],
        )
        self.assertEqual(legacy, "台词 kw1 画面 摘要 e1")

    def test_legacy_empty(self):
        self.assertEqual(build_legacy_text(), "")


if __name__ == "__main__":
    unittest.main()
