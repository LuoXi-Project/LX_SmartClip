import asyncio
import unittest

from app.agent.intent_preflight import (
    _extract_search_terms,
    _is_exploratory_query,
    _is_usable_keyword,
    run_intent_preflight,
)


class IntentPreflightTests(unittest.TestCase):
    def test_exploratory_movie_query(self) -> None:
        msg = "帮我找下适合做电影剪辑的视频"
        self.assertTrue(_is_exploratory_query(msg))
        terms = _extract_search_terms(msg)
        self.assertEqual(terms, [])

    def test_generic_keyword_filtered(self) -> None:
        self.assertFalse(_is_usable_keyword("电影"))
        self.assertFalse(_is_usable_keyword("视频剪辑"))
        self.assertTrue(_is_usable_keyword("洁柔面巾纸"))

    def test_concrete_product_still_extracted(self) -> None:
        terms = _extract_search_terms("选洁柔面巾纸的3个视频，做30秒口播方案")
        self.assertTrue(any("洁柔" in t for t in terms))

    def test_run_preflight_skips_exploratory(self) -> None:
        async def _run() -> None:
            r = await run_intent_preflight(
                "帮我找下适合做电影剪辑的视频",
                selected_video_ids=[],
            )
            self.assertIsNone(r)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
