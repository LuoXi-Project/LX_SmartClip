"""FaissVectorDB 多子空间（4 槽）单测。

不依赖真实 embedding API：用确定性合成向量验证 4 槽读写、RRF 融合、legacy 兼容、删除计数。
"""
import json
import os
import shutil
import tempfile
import unittest

import numpy as np

from app.core.vector_db.faiss_db import FaissVectorDB, _RRF_K


def _make_vec(seed: int, dim: int = 16) -> list:
    """确定性单位向量（与真实库的归一化假设一致）。"""
    rng = np.random.RandomState(seed)
    v = rng.randn(dim).astype("float32")
    n = float(np.linalg.norm(v))
    return [float(x / n) for x in v]


# 固定的 query 方向与正交方向，用于精确控制余弦相似度
_Q_DIR = None
_ORTHO_DIR = None


def _ortho_dirs(dim: int = 16):
    """返回 (query_dir, ortho_dir)，二者单位正交。惰性初始化。"""
    global _Q_DIR, _ORTHO_DIR
    if _Q_DIR is None or len(_Q_DIR) != dim:
        rng = np.random.RandomState(42)
        q = rng.randn(dim).astype("float32")
        q = q / np.linalg.norm(q)
        o = rng.randn(dim).astype("float32")
        o = o - np.dot(o, q) * q  # Gram-Schmidt 去掉 q 分量
        o = o / np.linalg.norm(o)
        _Q_DIR = q
        _ORTHO_DIR = o
    return _Q_DIR, _ORTHO_DIR


def _vec_with_cos(cos_sim: float, dim: int = 16) -> list:
    """构造单位向量，使其与 query_dir 的余弦相似度精确等于 cos_sim。

    v = normalize(cos*q_dir + sin*ortho_dir)，因 q_dir⊥ortho_dir 且均单位，
    归一化前 ‖v‖²=cos²+sin²=1，故 v·q_dir = cos。从而可精确控制 FAISS 排序。
    """
    q, o = _ortho_dirs(dim)
    sin_sim = float(np.sqrt(max(0.0, 1.0 - cos_sim * cos_sim)))
    v = cos_sim * q + sin_sim * o
    return [float(x) for x in v]


def _query_vec(dim: int = 16) -> list:
    """返回固定 query 方向（即 _ortho_dirs 的 q_dir）。"""
    q, _ = _ortho_dirs(dim)
    return [float(x) for x in q]


class _FaissTestBase(unittest.TestCase):
    DIM = 16

    def setUp(self):
        faiss = __import__("faiss")
        assert faiss is not None
        self.tmp = tempfile.mkdtemp(prefix="faiss_multivec_")
        self.db_path = os.path.join(self.tmp, "smartclip.db")
        # 建一个空 clips 表，search 的 video_ids 过滤会查它
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE clips (id TEXT PRIMARY KEY, video_id TEXT)")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _new_db(self):
        return FaissVectorDB(db_path=self.db_path, vector_dimension=self.DIM)


class TestMultiSubspaceWriteRead(_FaissTestBase):
    def test_add_multi_then_get_multi(self):
        db = self._new_db()
        cid = "clip-1"
        vecs = {
            "asr": _make_vec(1, self.DIM),
            "vlm": _make_vec(2, self.DIM),
            "abstract": _make_vec(3, self.DIM),
        }
        db.add_embedding_multi(cid, vecs)

        got = db.get_embedding_multi(cid)
        self.assertEqual(set(got.keys()), {"asr", "vlm", "abstract"})
        for sub in ("asr", "vlm", "abstract"):
            self.assertEqual(len(got[sub]), self.DIM)
            np.testing.assert_allclose(got[sub], vecs[sub], rtol=1e-5)

    def test_get_embedding_prefers_abstract_then_legacy(self):
        db = self._new_db()
        cid = "clip-1"
        legacy_vec = _make_vec(10, self.DIM)
        # 仅写 legacy
        db.add_embedding_multi(cid, {"legacy": legacy_vec})
        self.assertEqual(db.get_embedding(cid), legacy_vec)

        # 再写 abstract，应优先返回 abstract
        abs_vec = _make_vec(11, self.DIM)
        db.add_embedding_multi(cid, {"abstract": abs_vec})
        self.assertEqual(db.get_embedding(cid), abs_vec)

    def test_add_embedding_single_writes_abstract(self):
        db = self._new_db()
        cid = "clip-1"
        v = _make_vec(5, self.DIM)
        db.add_embedding(cid, v)
        # 单向量接口应落到 abstract
        self.assertEqual(db.subspace_count("abstract"), 1)
        self.assertEqual(db.subspace_count("asr"), 0)
        self.assertEqual(db.get_embedding(cid), v)

    def test_unknown_subspace_ignored(self):
        db = self._new_db()
        v = _make_vec(1, self.DIM)
        db.add_embedding_multi("c1", {"bogus": v, "asr": v})
        self.assertEqual(db.subspace_count("asr"), 1)
        self.assertNotIn("bogus", {s for s in db.SUBSPACES})


class TestCountAndDelete(_FaissTestBase):
    def test_embedding_count_dedup_across_subspaces(self):
        db = self._new_db()
        db.add_embedding_multi("c1", {"asr": _make_vec(1, self.DIM), "vlm": _make_vec(2, self.DIM)})
        db.add_embedding_multi("c2", {"abstract": _make_vec(3, self.DIM)})
        db.add_embedding_multi("c3", {"legacy": _make_vec(4, self.DIM)})
        # 3 个 clip 各至少一个子空间
        self.assertEqual(db.embedding_count(), 3)
        # subspace_count 分开统计
        self.assertEqual(db.subspace_count("asr"), 1)
        self.assertEqual(db.subspace_count("vlm"), 1)
        self.assertEqual(db.subspace_count("abstract"), 1)
        self.assertEqual(db.subspace_count("legacy"), 1)

    def test_delete_clears_all_subspaces(self):
        db = self._new_db()
        db.add_embedding_multi(
            "c1",
            {
                "asr": _make_vec(1, self.DIM),
                "vlm": _make_vec(2, self.DIM),
                "abstract": _make_vec(3, self.DIM),
                "legacy": _make_vec(4, self.DIM),
            },
        )
        removed = db.delete_embedding_multi("c1")
        self.assertEqual(removed, 4)
        self.assertEqual(db.get_embedding_multi("c1"), {})
        self.assertEqual(db.embedding_count(), 0)

    def test_delete_embeddings_batch(self):
        db = self._new_db()
        db.add_embedding_multi("c1", {"asr": _make_vec(1, self.DIM)})
        db.add_embedding_multi("c2", {"abstract": _make_vec(2, self.DIM)})
        db.add_embedding_multi("c3", {"vlm": _make_vec(3, self.DIM)})
        removed = db.delete_embeddings(["c1", "c2", "ghost"])
        self.assertEqual(removed, 2)
        self.assertEqual(db.embedding_count(), 1)


class TestRRFFusion(_FaissTestBase):
    """构造确定性场景验证 RRF 公式。"""

    def _seed_clip(self, db, cid, subs_with_seeds):
        """写入 clip 并让各子空间向量取不同 seed，便于控制近邻排序。"""
        db.add_embedding_multi(cid, {s: _make_vec(sd, self.DIM) for s, sd in subs_with_seeds.items()})

    def test_single_subspace_degrades_to_its_order(self):
        # 只有 legacy 有数据，融合应等于 legacy 排序
        db = self._new_db()
        q = _query_vec(self.DIM)
        # 用 _vec_with_cos 精确控制余弦相似度：a 最接近 q
        db.add_embedding_multi("a", {"legacy": _vec_with_cos(0.99, self.DIM)})
        db.add_embedding_multi("b", {"legacy": _vec_with_cos(0.50, self.DIM)})
        db.add_embedding_multi("c", {"legacy": _vec_with_cos(0.10, self.DIM)})
        result = db.search(q, top_k=3)
        # a 余弦最高，应排第一
        self.assertEqual(result[0], "a")
        self.assertEqual(set(result), {"a", "b", "c"})

    def test_clip_in_multiple_subspaces_ranks_higher(self):
        # 同一 clip 出现在多个子空间的 top 列表里，RRF 分数累加，排名更靠前
        db = self._new_db()
        q = _query_vec(self.DIM)
        # shared 在 3 个子空间里都接近 query（高余弦）
        shared_v = _vec_with_cos(0.95, self.DIM)
        db.add_embedding_multi("shared", {
            "asr": shared_v,
            "vlm": shared_v,
            "abstract": shared_v,
        })
        # only_asr 在 asr 子空间略更接近 query，但在 vlm/abstract 远离
        db.add_embedding_multi("only_asr", {
            "asr": _vec_with_cos(0.99, self.DIM),  # asr 子空间第一
            "vlm": _vec_with_cos(0.05, self.DIM),
            "abstract": _vec_with_cos(0.05, self.DIM),
        })
        result = db.search(q, top_k=2)
        # shared 三路累加应高于 only_asr 单路
        self.assertEqual(result[0], "shared")

    def test_rrf_formula_directly(self):
        # 直接喂排名列表，验证融合公式
        per_sub = {
            "asr": ["x", "y", "z"],
            "vlm": ["y", "z", "x"],
        }
        fused = FaissVectorDB._rrf_fuse(per_sub, top_k=3)
        # x: 1/60(asr r0) + 1/62(vlm r2) = 0.01667 + 0.01613 = 0.03280
        # y: 1/61(asr r1) + 1/60(vlm r0) = 0.01639 + 0.01667 = 0.03306  <- 最高
        # z: 1/62(asr r2) + 1/61(vlm r1) = 0.01613 + 0.01639 = 0.03352  <- 实际最高
        import math
        exp = {
            "x": 1 / _RRF_K + 1 / (_RRF_K + 2),
            "y": 1 / (_RRF_K + 1) + 1 / _RRF_K,
            "z": 1 / (_RRF_K + 2) + 1 / (_RRF_K + 1),
        }
        expected_order = sorted(exp, key=lambda k: exp[k], reverse=True)
        self.assertEqual(fused, expected_order)
        self.assertEqual(len(fused), 3)


class TestLegacyCompat(_FaissTestBase):
    def test_old_single_file_loads_into_legacy(self):
        # 模拟旧库：直接写一个 clip_embeddings.json（旧格式 {"embeddings": {...}}）
        legacy_path = os.path.join(self.tmp, "clip_embeddings.json")
        v = _make_vec(7, self.DIM)
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump({"embeddings": {"old-clip": v}}, f)

        db = self._new_db()
        # 旧数据应加载进 legacy 子空间
        self.assertEqual(db.subspace_count("legacy"), 1)
        got = db.get_embedding("old-clip")  # abstract 无，fallback legacy
        self.assertIsNotNone(got)
        np.testing.assert_allclose(got, v, rtol=1e-5)
        # 仍可被检索命中
        result = db.search(v, top_k=1)
        self.assertEqual(result, ["old-clip"])

    def test_legacy_not_overwritten_on_new_write(self):
        v = _make_vec(7, self.DIM)
        legacy_path = os.path.join(self.tmp, "clip_embeddings.json")
        with open(legacy_path, "w", encoding="utf-8") as f:
            json.dump({"embeddings": {"old-clip": v}}, f)

        db = self._new_db()
        # 写入新 clip 的 abstract，legacy 不应被破坏
        db.add_embedding_multi("new-clip", {"abstract": _make_vec(8, self.DIM)})
        self.assertEqual(db.subspace_count("legacy"), 1)
        self.assertEqual(db.subspace_count("abstract"), 1)
        self.assertEqual(db.embedding_count(), 2)


class TestVideoIdFilter(_FaissTestBase):
    def test_video_id_filter_narrows_results(self):
        db = self._new_db()
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.executemany("INSERT INTO clips(id, video_id) VALUES (?,?)", [
            ("a", "vid1"), ("b", "vid1"), ("c", "vid2"),
        ])
        conn.commit()
        conn.close()

        db.add_embedding_multi("a", {"asr": _make_vec(101, self.DIM)})
        db.add_embedding_multi("b", {"asr": _make_vec(102, self.DIM)})
        db.add_embedding_multi("c", {"asr": _make_vec(103, self.DIM)})

        q = _make_vec(100, self.DIM)
        result = db.search(q, top_k=5, video_ids=["vid1"])
        self.assertEqual(set(result), {"a", "b"})


class TestSubspaceFilter(_FaissTestBase):
    """指定子空间检索：subspaces 参数限定参与融合的子空间。"""

    def test_subspaces_limits_active_subspaces(self):
        db = self._new_db()
        q = _query_vec(self.DIM)
        # clip "asr_hit" 仅在 asr 子空间接近 query
        db.add_embedding_multi("asr_hit", {"asr": _vec_with_cos(0.99, self.DIM)})
        # clip "vlm_hit" 仅在 vlm 子空间接近 query
        db.add_embedding_multi("vlm_hit", {"vlm": _vec_with_cos(0.99, self.DIM)})

        # 只查 asr 子空间 → 应命中 asr_hit，不含 vlm_hit
        result_asr = db.search(q, top_k=5, subspaces=["asr"])
        self.assertIn("asr_hit", result_asr)
        self.assertNotIn("vlm_hit", result_asr)

        # 只查 vlm 子空间 → 应命中 vlm_hit，不含 asr_hit
        result_vlm = db.search(q, top_k=5, subspaces=["vlm"])
        self.assertIn("vlm_hit", result_vlm)
        self.assertNotIn("asr_hit", result_vlm)

    def test_subspaces_none_uses_all(self):
        db = self._new_db()
        q = _query_vec(self.DIM)
        db.add_embedding_multi("a", {"asr": _vec_with_cos(0.99, self.DIM)})
        db.add_embedding_multi("b", {"vlm": _vec_with_cos(0.99, self.DIM)})
        # 不指定 → 两个子空间都参与，a/b 都应出现
        result = db.search(q, top_k=5)
        self.assertIn("a", result)
        self.assertIn("b", result)

    def test_subspaces_empty_data_subspace_skipped(self):
        db = self._new_db()
        q = _query_vec(self.DIM)
        db.add_embedding_multi("a", {"asr": _vec_with_cos(0.99, self.DIM)})
        # 指定 asr + vlm，但 vlm 无数据 → 应自动跳过 vlm，不报错
        result = db.search(q, top_k=5, subspaces=["asr", "vlm"])
        self.assertEqual(result, ["a"])

    def test_subspaces_unknown_ignored(self):
        db = self._new_db()
        q = _query_vec(self.DIM)
        db.add_embedding_multi("a", {"asr": _vec_with_cos(0.99, self.DIM)})
        # 含未知子空间名 → 被忽略，asr 仍生效
        result = db.search(q, top_k=5, subspaces=["asr", "bogus"])
        self.assertEqual(result, ["a"])


class TestDimensionMismatch(_FaissTestBase):
    def test_dim_mismatch_raises(self):
        db = self._new_db()
        with self.assertRaises(ValueError):
            db.add_embedding_multi("c1", {"asr": [0.1, 0.2, 0.3]})
        with self.assertRaises(ValueError):
            db.search([0.1] * 5, top_k=1)


if __name__ == "__main__":
    unittest.main()
