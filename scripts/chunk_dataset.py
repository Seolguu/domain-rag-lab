#!/usr/bin/env python3
"""DATA-ROOT 데이터셋(원천 금융상품 + CoT 라벨링)을 RAG 청크로 변환한다.

청크 전략은 app/services/chunker.py 의 TextChunker 와 동일하다
(문단('\\n\\n') 기준 그리디 패킹 -> CHUNK_SIZE 초과 시 하드 분할 -> CHUNK_OVERLAP 접두 중첩).
외부 의존성 없이 표준 라이브러리만 사용한다.

사용법:
    python3 scripts/chunk_dataset.py                # 기본: DATA-ROOT -> data/chunks/
    python3 scripts/chunk_dataset.py --src DATA-ROOT --out data/chunks --size 500 --overlap 80
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from pathlib import Path

# ── 청크기 (app/services/chunker.py 미러) ──────────────────────────────


class TextChunker:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 80):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            candidate = f"{current}\n\n{para}".strip() if current else para
            if len(candidate) <= self.chunk_size:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(para) <= self.chunk_size:
                current = para
            else:
                chunks.extend(self._split_long_paragraph(para))
                current = ""
        if current:
            chunks.append(current)
        return self._apply_overlap(chunks)

    def _split_long_paragraph(self, para: str) -> list[str]:
        result = []
        start = 0
        while start < len(para):
            end = start + self.chunk_size
            result.append(para[start:end].strip())
            start = end
        return [x for x in result if x]

    def _apply_overlap(self, chunks: list[str]) -> list[str]:
        if not chunks or self.chunk_overlap <= 0:
            return chunks
        overlapped: list[str] = []
        for idx, chunk in enumerate(chunks):
            if idx == 0:
                overlapped.append(chunk)
                continue
            prev = chunks[idx - 1]
            prefix = prev[-self.chunk_overlap:] if len(prev) > self.chunk_overlap else prev
            overlapped.append(f"{prefix}\n{chunk}".strip())
        return overlapped


# ── JSON -> 텍스트 렌더링 ─────────────────────────────────────────────

EMPTY = {"", "정보 없음", "비대상", "무", "-", "없음", "해당 없음"}

SECURITIES_LABELS = {
    "product_name": "상품명",
    "product_type": "상품유형",
    "protected_type": "원금보장",
    "maturity_type": "만기",
    "income_rate": "수익률",
    "risk_grade": "위험등급",
    "tax_type": "세제",
    "payment_type": "납입방식",
    "loss_rate": "손실률",
    "liquidity_conditions": "유동성",
}

INSURANCE_LABELS = {
    "company": "보험사",
    "mother_product_name": "모상품명",
    "product_full_name": "상품 전체명",
    "product_type": "상품유형",
    "rider_type": "특약유형",
    "product_period": "보험기간",
    "disclosure_type": "고지유형",
    "renewable_type": "갱신유형",
    "refund_type": "환급유형",
    "refund_condition": "환급조건",
    "payment_type": "납입방식",
    "payment_period": "납입기간",
    "payment_conditions1": "지급조건1",
    "payment_conditions2": "지급조건2",
    "payment_conditions3": "지급조건3",
    "payment_conditions4": "지급조건4",
    "payment_conditions5": "지급조건5",
    "payment_conditions6": "지급조건6",
    "payment_conditions7": "지급조건7",
    "exclusion_items": "면책사항",
    "years_of_hospitalization_surgery": "입원·수술 기간",
    "srarting_age": "가입시작연령",
    "eligible_age": "가입가능연령",
    "tax_type": "세제",
    "insured_amount": "보험가입금액",
    "minimum_insured _premium": "최저가입보험료",
    "minimum_guarantee": "최저보증이율",
    "payment_flexibility": "납입유연성",
    "additional_payment": "추가납입",
    "early_withdrawal": "중도인출",
    "product_switching": "상품전환",
}

FREE_TEXT_FIELDS = ("investment_strategy", "product_features")


def clean(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def is_empty(v: str) -> bool:
    return v.strip() in EMPTY


def render_product(data: dict, kind: str) -> tuple[str, str]:
    """(title, text) 반환. kind: '증권' | '보험'"""
    labels = SECURITIES_LABELS if kind == "증권" else INSURANCE_LABELS
    title = clean(data.get("product_name")) or clean(data.get("product_full_name")) or "(제목없음)"

    lines = [f"# {title}"]  # 제목을 첫 속성 블록에 붙여 외톨이 청크 방지
    for key, label in labels.items():
        val = clean(data.get(key))
        if val and not is_empty(val):
            val = " ".join(val.split())  # 개행/중복공백 정리
            lines.append(f"- {label}: {val}")

    blocks = ["\n".join(lines)]
    for key in FREE_TEXT_FIELDS:
        val = clean(data.get(key))
        if val and not is_empty(val):
            heading = "투자전략" if key == "investment_strategy" else "상품특징"
            blocks.append(f"## {heading}\n{val}")

    return title, "\n\n".join(blocks)


def render_cot(data: dict) -> tuple[str, str]:
    cat = clean(data.get("category"))
    qtype = clean(data.get("query_type"))
    cid = clean(data.get("cot_id"))
    title = f"[{cat}] {qtype} 상담사례 #{cid}".strip()

    demo = " / ".join(
        x for x in (clean(data.get("gender")), clean(data.get("age"))) if x and not is_empty(x)
    )
    head = f"# {title}"
    if demo:
        head += f"\n상담대상: {demo}"
    # 제목/상담대상을 질문 블록에 붙여 외톨이 청크 방지
    parts = [f"{head}\n## 질문\n{clean(data.get('question'))}"]

    steps = [clean(data.get(f"cot{i}")) for i in range(1, 8)]
    steps = [s for s in steps if s and not is_empty(s)]
    for i, s in enumerate(steps, 1):
        parts.append(f"## 추론 {i}\n{s}")

    ans = clean(data.get("answer"))
    if ans:
        parts.append(f"## 답변\n{ans}")

    names = data.get("product_names") or []
    if isinstance(names, list) and names:
        parts.append("## 추천상품\n" + "\n".join(f"- {clean(n)}" for n in names))

    return title, "\n\n".join(parts)


# ── 파이프라인 ───────────────────────────────────────────────────────


def doc_id_for(root: Path, path: Path) -> str:
    rel = path.relative_to(root).as_posix()
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:10]
    return f"{path.stem}-{digest}"


def classify(rel_parts: tuple[str, ...]) -> tuple[str, str] | None:
    """상대경로 조각 -> (collection, kind). 대상 아니면 None."""
    joined = "/".join(unicodedata.normalize("NFC", p) for p in rel_parts)
    if "원천데이터" in joined:
        if "증권" in joined:
            return "products", "증권"
        if "보험" in joined:
            return "products", "보험"
        return "products", "기타"
    if "CoT" in joined or "라벨링데이터" in joined:
        return "cot", "cot"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="DATA-ROOT")
    ap.add_argument("--out", default="data/chunks")
    ap.add_argument("--size", type=int, default=500)
    ap.add_argument("--overlap", type=int, default=80)
    args = ap.parse_args()

    root = Path(args.src).resolve()
    out_dir = Path(args.out).resolve()
    if not root.is_dir():
        print(f"[error] src 없음: {root}", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    chunker = TextChunker(args.size, args.overlap)
    writers: dict[str, list[dict]] = {"products": [], "cot": []}
    stats = {
        "docs": 0,
        "skipped": 0,
        "parse_errors": 0,
        "by_kind": {},
        "chunks": {"products": 0, "cot": 0},
    }

    for path in sorted(root.rglob("*.json")):
        rel_parts = path.relative_to(root).parts
        target = classify(rel_parts)
        if target is None:
            stats["skipped"] += 1
            continue
        collection, kind = target

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[warn] JSON 파싱 실패: {path.name}: {e}", file=sys.stderr)
            stats["parse_errors"] += 1
            continue

        if collection == "cot":
            title, text = render_cot(data)
        else:
            title, text = render_product(data, kind)

        chunks = chunker.split_text(text)
        if not chunks:
            stats["skipped"] += 1
            continue

        document_id = doc_id_for(root, path)
        stats["docs"] += 1
        stats["by_kind"][kind] = stats["by_kind"].get(kind, 0) + 1
        stats["chunks"][collection] += len(chunks)

        for idx, content in enumerate(chunks):
            writers[collection].append(
                {
                    "chunk_id": f"{document_id}-chunk-{idx}",
                    "document_id": document_id,
                    "title": title,
                    "chunk_index": idx,
                    "content": content,
                    "domain": "finance",
                    "category": kind,
                    "source_path": path.relative_to(root).as_posix(),
                }
            )

    for collection, rows in writers.items():
        fp = out_dir / f"{collection}.jsonl"
        with fp.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        lengths = [len(r["content"]) for r in rows]
        avg = round(sum(lengths) / len(lengths), 1) if lengths else 0
        print(f"{fp.relative_to(Path.cwd()) if fp.is_relative_to(Path.cwd()) else fp}: "
              f"{len(rows)} chunks (avg {avg} chars, max {max(lengths) if lengths else 0})")

    (out_dir / "summary.json").write_text(
        json.dumps(
            {"chunk_size": args.size, "chunk_overlap": args.overlap, **stats},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
