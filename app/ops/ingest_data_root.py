"""Chunk and ingest the DATA-ROOT dataset (금융상품 / CoT 라벨링 / 소비자) into
PostgreSQL (keyword search) and Qdrant (vector search).

DATA-ROOT is not part of the git repo; it must be copied under ./data first
(so the api container sees it at /app/data/DATA-ROOT via the existing bind
mount), then run inside the api container:

    docker compose exec api python -m app.ops.ingest_data_root

Re-running is safe for PostgreSQL (chunk_id is unique, conflicts are
skipped) but Qdrant points get a fresh random id each run, so re-running
without clearing the collection will duplicate vectors.
"""

from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import SessionLocal
from app.models.document_chunk import DocumentChunk
from app.services.chunker import TextChunker
from app.services.embedder import EmbeddingService
from app.services.vector_store import VectorStore
from app.core.config import settings

DATA_ROOT = Path("/app/data/DATA-ROOT")
PRODUCT_DIR = DATA_ROOT / "1.상품"
COT_DIR = DATA_ROOT / "02.라벨링데이터" / "1.CoT"
CONSUMER_CSV = DATA_ROOT / "02.라벨링데이터" / "2.소비자" / "소비자(Sampling).csv"

DOMAIN = "finance"
BATCH_SIZE = 500


def iter_product_docs():
    for path in sorted(PRODUCT_DIR.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        title = data.get("product_name") or data.get("product_full_name") or path.stem
        lines = [f"{key}: {value}" for key, value in data.items() if value not in (None, "")]
        content = "\n\n".join(lines)
        document_id = f"product-{uuid.uuid5(uuid.NAMESPACE_URL, str(path)).hex[:16]}"
        yield document_id, title, content


def iter_cot_docs():
    for path in sorted(COT_DIR.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        title = f"CoT-{data.get('category', '')}-{data.get('query_type', '')}-{data.get('cot_id', path.stem)}"
        parts = [
            f"질문: {data.get('question', '')}",
            f"고객 분석: {data.get('cot1', '')}",
            f"조건 분석: {data.get('cot2', '')}",
            f"상품 매칭: {data.get('cot3', '')}",
            f"답변: {data.get('answer', '')}",
        ]
        if data.get("product_names"):
            parts.append("추천 상품: " + ", ".join(data["product_names"]))
        content = "\n\n".join(p for p in parts if p.strip())
        document_id = f"cot-{data.get('cot_id', path.stem)}"
        yield document_id, title, content


def iter_consumer_docs():
    with CONSUMER_CSV.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            customer_id = row.get("customer_id", f"row{idx}")
            seq = row.get("customer_seq", "0")
            lines = [f"{key}: {value}" for key, value in row.items() if value not in (None, "")]
            content = "\n".join(lines)
            title = f"고객프로파일-{customer_id[:12]}-{seq}"
            document_id = f"consumer-{customer_id[:16]}-{seq}-{idx}"
            yield document_id, title, content


def flush(chunk_docs: list[dict], embedder: EmbeddingService, vector_store: VectorStore, session) -> None:
    if not chunk_docs:
        return

    vectors = embedder.embed_texts([c["content"] for c in chunk_docs])
    vector_store.upsert_chunks(chunk_docs, vectors)

    for row in chunk_docs:
        stmt = pg_insert(DocumentChunk).values(**row)
        stmt = stmt.on_conflict_do_nothing(index_elements=["chunk_id"])
        session.execute(stmt)
    session.commit()


def ingest(label: str, doc_iter, chunker: TextChunker, embedder: EmbeddingService, vector_store: VectorStore) -> None:
    session = SessionLocal()
    batch: list[dict] = []
    doc_count = 0
    chunk_count = 0

    try:
        for document_id, title, content in doc_iter:
            chunks = chunker.split_text(content)
            doc_count += 1
            for idx, chunk in enumerate(chunks):
                batch.append(
                    {
                        "chunk_id": f"{document_id}-chunk-{idx}",
                        "document_id": document_id,
                        "title": title,
                        "content": chunk,
                        "chunk_index": idx,
                        "domain": DOMAIN,
                    }
                )
                chunk_count += 1

            if len(batch) >= BATCH_SIZE:
                flush(batch, embedder, vector_store, session)
                batch = []
                print(f"[{label}] {doc_count} docs / {chunk_count} chunks so far", flush=True)

        flush(batch, embedder, vector_store, session)
    finally:
        session.close()

    print(f"[{label}] done: {doc_count} docs -> {chunk_count} chunks")


def main() -> None:
    chunker = TextChunker()
    embedder = EmbeddingService(settings.embedding_model)
    vector_store = VectorStore()

    ingest("상품", iter_product_docs(), chunker, embedder, vector_store)
    ingest("CoT", iter_cot_docs(), chunker, embedder, vector_store)
    ingest("소비자", iter_consumer_docs(), chunker, embedder, vector_store)


if __name__ == "__main__":
    main()
