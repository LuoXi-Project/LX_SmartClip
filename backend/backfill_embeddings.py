"""一次性维护脚本：为缺失向量的 clip 批量补 embed（多子空间版）。

使用：
    cd backend
    python backfill_embeddings.py                  # 默认 batch=10, 并发 4
    python backfill_embeddings.py --batch 32 --workers 2
    python backfill_embeddings.py --dry-run        # 只统计不调用 API
    python backfill_embeddings.py --limit 100      # 只处理前 100 个（测试用）
    python backfill_embeddings.py --subspace asr   # 只补某一个子空间（调试用）

特性：
- 多子空间：每个 clip 写 asr/vlm/abstract 三个子空间向量（详见 sub_texts.build_sub_texts）
- 只补「SQLite 中存在 + 前 3 子空间任一缺失」的 clip；已齐全的不会重复 embed
- 逐子空间调用 embed（火山方舟无 batch），每 batch 写一次盘（原子写）
- 失败的 clip 收集到最后打印，可重跑本脚本自动续上（脚本每次都重新算缺失集）
- Ctrl+C 安全：当前 batch 完成后退出
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill")

from app.db.database import DB_PATH
from app.core.embedder import Embedder
from app.core.vector_db.faiss_db import FaissVectorDB
from app.core.vector_db.sub_texts import WRITABLE_SUBSPACES, build_sub_texts, non_empty_subspaces


def _read_cfg(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _build_sub_texts(row: sqlite3.Row) -> dict:
    """复用 process_pipeline 的子空间文本拼接逻辑（共用 sub_texts.build_sub_texts）。"""
    return build_sub_texts(
        asr_text=row["asr_text"] or "",
        vlm_description=row["vlm_description"] or "",
        abstract_summary=row["abstract_summary"] or "",
        keywords=row["keywords"],
        emotion_tags=row["emotion_tags"],
    )


def collect_missing(
    vdb: FaissVectorDB, limit: int, only_sub: Optional[str] = None
) -> List[Tuple[str, dict]]:
    """返回 [(clip_id, sub_texts), ...]。

    only_sub: 若指定，只补该子空间缺失的（其它子空间不写）。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, asr_text, vlm_description, abstract_summary, keywords, emotion_tags "
            "FROM clips ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()

    out: List[Tuple[str, dict]] = []
    for r in rows:
        cid = r["id"]
        sub_texts = _build_sub_texts(r)
        wanted = non_empty_subspaces(sub_texts)
        if not wanted:
            continue

        # 判断哪些子空间需要补
        if only_sub:
            if only_sub not in wanted:
                continue
            if vdb.get_embedding_multi(cid).get(only_sub):
                continue
            todo = [only_sub]
        else:
            existing = vdb.get_embedding_multi(cid)
            todo = [s for s in wanted if not existing.get(s)]
            if not todo:
                continue

        # 只保留待补子空间的文本
        filtered = {s: sub_texts[s] for s in todo}
        out.append((cid, filtered))
        if limit and len(out) >= limit:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10, help="每批处理的 clip 数")
    ap.add_argument("--workers", type=int, default=4, help="并发批数")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个（0=全部）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不调用 API")
    ap.add_argument("--max-per-sec", type=int, default=0, help="每秒最多处理多少个 clip（0=不限）")
    ap.add_argument(
        "--subspace",
        choices=list(WRITABLE_SUBSPACES),
        default=None,
        help="只补指定子空间（默认补齐所有缺失子空间）",
    )
    ap.add_argument(
        "--purge-legacy",
        action="store_true",
        help="补齐的 clip 若三子空间(asr/vlm/abstract)均已齐全，删除其 legacy 旧向量以释放空间",
    )
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        embed_base_url = _read_cfg(conn, "embedding_base_url", "https://api.openai.com/v1")
        embed_api_key = _read_cfg(conn, "embedding_api_key", "")
        embed_model = _read_cfg(conn, "embedding_model", "text-embedding-3-small")
        vector_dim = int(_read_cfg(conn, "vector_dimension", "1024"))
    finally:
        conn.close()

    if not embed_api_key:
        log.error("config 中未配置 embedding_api_key，无法补 embed。请先在设置页配置。")
        sys.exit(2)

    vdb = FaissVectorDB(db_path=DB_PATH, vector_dimension=vector_dim)
    for s in vdb.SUBSPACES:
        log.info("子空间 %s: %d 个向量", s, vdb.subspace_count(s))

    missing = collect_missing(vdb, args.limit, only_sub=args.subspace)
    log.info("需要补 embed 的 clip 数: %d", len(missing))

    if not missing:
        log.info("没有需要补的，已完整。")
        return

    if args.dry_run:
        log.info("--dry-run 模式，不调用 API。前 5 条:")
        for cid, subs in missing[:5]:
            log.info("  %s 子空间=%s", cid, list(subs.keys()))
            for s, t in subs.items():
                log.info("    %s len=%d: %s", s, len(t), t[:80])
        return

    embedder = Embedder(
        base_url=embed_base_url,
        api_key=embed_api_key,
        model=embed_model,
        request_timeout_sec=120.0,
        volc_output_dimensions=vector_dim,
    )

    # 切分 batch
    batches: List[List[Tuple[str, dict]]] = []
    for i in range(0, len(missing), args.batch):
        batches.append(missing[i : i + args.batch])
    log.info("切分为 %d 个 batch（每 batch %d clip），并发 %d", len(batches), args.batch, args.workers)

    done = 0
    failed: List[Tuple[str, str]] = []
    lock_for_save = __import__("threading").Lock()
    t0 = time.perf_counter()

    def process_batch(batch: List[Tuple[str, dict]]):
        """逐 clip 逐子空间 embed，写一次盘。"""
        nonlocal done
        all_vecs: List[tuple] = []  # [(cid, {sub: vec}), ...]
        batch_failed: List[Tuple[str, str]] = []
        for cid, subs in batch:
            try:
                vecs: dict = {}
                for sub, text in subs.items():
                    vecs[sub] = embedder.embed(text)
                all_vecs.append((cid, vecs))
            except Exception as e:
                batch_failed.append((cid, str(e)))

        if all_vecs:
            with lock_for_save:
                for cid, vecs in all_vecs:
                    vdb.add_embedding_multi(cid, vecs)
                    # 可选：补齐后若三子空间齐全，删除 legacy 旧向量
                    if args.purge_legacy:
                        existing = vdb.get_embedding_multi(cid)
                        if all(existing.get(s) for s in WRITABLE_SUBSPACES) and existing.get("legacy"):
                            vdb.delete_subspace(cid, "legacy")
        return len(all_vecs), batch_failed

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(process_batch, b): b for b in batches}
            for fut in as_completed(futures):
                batch = futures[fut]
                added, batch_failed = fut.result()
                if batch_failed:
                    failed.extend(batch_failed)
                    log.warning("batch %d 个失败", len(batch_failed))
                done += added
                elapsed = time.perf_counter() - t0
                rate = done / elapsed if elapsed > 0 else 0
                log.info(
                    "进度 %d/%d (%.1f%%) 用时 %.0fs 速率 %.1f/s 失败 %d",
                    done, len(missing), 100.0 * done / len(missing),
                    elapsed, rate, len(failed),
                )
                # 限速
                if args.max_per_sec > 0:
                    time.sleep(max(0, done / args.max_per_sec - elapsed))
    except KeyboardInterrupt:
        log.warning("收到 Ctrl+C，已完成的 batch 已落盘，未完成的可在下次重跑续上")

    log.info("=" * 60)
    log.info("完成: 成功 %d, 失败 %d, 总耗时 %.0fs", done, len(failed), time.perf_counter() - t0)
    for s in vdb.SUBSPACES:
        log.info("子空间 %s: %d 个向量", s, vdb.subspace_count(s))
    if failed:
        log.warning("失败 clip（前 20）:")
        for cid, err in failed[:20]:
            log.warning("  %s -> %s", cid, err)
        log.warning("可重跑本脚本自动续上失败的（已成功的不会重复 embed）")

    embedder.close()


if __name__ == "__main__":
    main()
