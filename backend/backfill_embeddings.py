"""一次性维护脚本：为缺失向量的 clip 批量补 embed。

使用：
    cd backend
    python backfill_embeddings.py                  # 默认 batch=64, 并发 4
    python backfill_embeddings.py --batch 32 --workers 2
    python backfill_embeddings.py --dry-run        # 只统计不调用 API
    python backfill_embeddings.py --limit 100      # 只处理前 100 个（测试用）

特性：
- 只补「SQLite 中存在 + 向量库中缺失」的 clip，已存在的不会重复 embed
- 批量调用 embed_batch（OpenAI 单请求多文本，省调用次数）
- 每个 batch 写一次盘（FaissVectorDB.add_embedding 已原子写）
- 失败的 clip 收集到最后打印，可重跑本脚本自动续上（脚本每次都重新算缺失集）
- Ctrl+C 安全：当前 batch 完成后退出
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("backfill")

from app.db.database import DB_PATH
from app.core.embedder import Embedder
from app.core.vector_db.faiss_db import FaissVectorDB


def _read_cfg(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _build_text(row: sqlite3.Row) -> str:
    """复用 process_pipeline 的五路文本拼接逻辑。"""
    def _join_tags(raw):
        if not raw:
            return ""
        try:
            v = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(v, list):
                return " ".join(str(x) for x in v if x)
            return str(v)
        except Exception:
            return str(raw)

    parts = [
        row["asr_text"] or "",
        row["vlm_description"] or "",
        row["abstract_summary"] or "",
        _join_tags(row["keywords"]),
        _join_tags(row["emotion_tags"]),
    ]
    return " ".join(p for p in parts if p and p.strip()).strip()


def collect_missing(vdb: FaissVectorDB, limit: int) -> List[Tuple[str, str]]:
    """返回 [(clip_id, text), ...]，文本为空的跳过。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, asr_text, vlm_description, abstract_summary, keywords, emotion_tags "
            "FROM clips ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()

    existing = set(vdb._clip_ids)
    out: List[Tuple[str, str]] = []
    for r in rows:
        if r["id"] in existing:
            continue
        text = _build_text(r)
        if not text:
            continue
        out.append((r["id"], text))
        if limit and len(out) >= limit:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10, help="每个 API 请求的文本数（火山方舟上限 10）")
    ap.add_argument("--workers", type=int, default=4, help="并发 API 请求数")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个（0=全部）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不调用 API")
    ap.add_argument("--max-per-sec", type=int, default=0, help="每秒最多处理多少个文本（0=不限）")
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
    log.info("当前向量库已有 %d 个向量", vdb.embedding_count())

    missing = collect_missing(vdb, args.limit)
    log.info("需要补 embed 的 clip 数: %d", len(missing))

    if not missing:
        log.info("没有需要补的，已完整。")
        return

    if args.dry_run:
        log.info("--dry-run 模式，不调用 API。前 5 条:")
        for cid, text in missing[:5]:
            log.info("  %s len=%d: %s", cid, len(text), text[:80])
        return

    embedder = Embedder(
        base_url=embed_base_url,
        api_key=embed_api_key,
        model=embed_model,
        request_timeout_sec=120.0,
        volc_output_dimensions=vector_dim,
    )

    # 切分 batch
    batches: List[List[Tuple[str, str]]] = []
    for i in range(0, len(missing), args.batch):
        batches.append(missing[i : i + args.batch])
    log.info("切分为 %d 个 batch（每 batch %d），并发 %d", len(batches), args.batch, args.workers)

    done = 0
    failed: List[Tuple[str, str]] = []
    lock_for_save = __import__("threading").Lock()
    t0 = time.perf_counter()
    last_min = -1

    def process_batch(batch: List[Tuple[str, str]]):
        nonlocal done
        ids = [cid for cid, _ in batch]
        texts = [t for _, t in batch]
        try:
            vecs = embedder.embed_batch(texts)
            if len(vecs) != len(texts):
                raise RuntimeError(f"返回向量数 {len(vecs)} != 输入数 {len(texts)}")
            # 批量写入（一次 rebuild + 落盘），大幅减少 100MB 文件重写次数
            with lock_for_save:
                added = vdb.add_embeddings(list(zip(ids, vecs)))
            return added, None
        except Exception as e:
            return 0, str(e)

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(process_batch, b): b for b in batches}
            for fut in as_completed(futures):
                added, err = fut.result()
                if err:
                    ids = [cid for cid, _ in futures[fut]]
                    for cid in ids:
                        failed.append((cid, err))
                    log.warning("batch %d 个失败: %s", len(ids), err)
                else:
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
    log.info("向量库现有 %d 个向量", vdb.embedding_count())
    if failed:
        log.warning("失败 clip（前 20）:")
        for cid, err in failed[:20]:
            log.warning("  %s -> %s", cid, err)
        log.warning("可重跑本脚本自动续上失败的（已成功的不会重复 embed）")

    embedder.close()


if __name__ == "__main__":
    main()
