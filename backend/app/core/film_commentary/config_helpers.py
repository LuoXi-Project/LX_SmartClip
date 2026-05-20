from __future__ import annotations

from dataclasses import dataclass

from app.core.embedder import Embedder
from app.core.llm import LLMClient
from app.core.vector_db.faiss_db import FaissVectorDB
from app.core.film_commentary.db import read_config_map
from app.db.database import DB_PATH


@dataclass
class FilmRuntimeConfig:
    llm: LLMClient
    embedder: Embedder
    vector_db: FaissVectorDB
    vector_dim: int
    match_top_k: int


async def load_runtime_config() -> FilmRuntimeConfig:
    cfg = await read_config_map()
    vector_dim = int(cfg.get("vector_dimension") or "1024")
    llm = LLMClient(
        base_url=cfg.get("llm_base_url") or "https://api.openai.com/v1",
        api_key=cfg.get("llm_api_key") or "",
        model=cfg.get("llm_model") or "gpt-4o-mini",
        temperature=float(cfg.get("llm_temperature") or "0.7"),
        max_tokens=int(cfg.get("llm_max_tokens") or "20480"),
    )
    embedder = Embedder(
        base_url=cfg.get("embedding_base_url") or "https://api.openai.com/v1",
        api_key=cfg.get("embedding_api_key") or "",
        model=cfg.get("embedding_model") or "text-embedding-3-small",
        volc_output_dimensions=vector_dim,
    )
    vector_db = FaissVectorDB(DB_PATH, vector_dimension=vector_dim)
    top_k = int(cfg.get("match_top_k") or "12")
    return FilmRuntimeConfig(
        llm=llm,
        embedder=embedder,
        vector_db=vector_db,
        vector_dim=vector_dim,
        match_top_k=max(top_k, 16),
    )
