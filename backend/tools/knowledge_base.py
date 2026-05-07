"""Canon knowledge base — FR-09 (Phase 1.6 foundation + Phase 2.9 per-church).

On startup, ingests every `backend/skills/worker/denomination_*/SKILL.md`
into a global ChromaDB collection `kb_canon`. Each SKILL.md is chunked into
~500-token sections (split by markdown ## headings, falling back to character
limits) with metadata `{denomination, source_path, section_heading}`.

Phase 2.9 adds per-church collections (`kb_{church_id}`) that are populated
from documents uploaded via the KB UI / API. The combined search always queries
both the global canon and the relevant church collection and merges results
by score.

Idempotent: if `kb_canon` already exists with documents, ingestion is skipped.
Per-church ingestion is also idempotent: re-ingesting a file replaces its
existing chunks rather than duplicating them.

Public API:
    ingest_canon_skills() -> int                          # global canon
    ingest_church_kb(church_id, file_path) -> int         # per-church
    delete_church_kb_file(church_id, filename) -> int
    kb_search_church(query, church_id, k=3) -> List[KBHit]
    kb_search(query, church_id=None, k=3, denomination=None) -> List[KBHit]

KBHit = {text, citation, score, source_path, denomination, section_heading,
         church_id, source_filename}
"""
from __future__ import annotations
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions


# Reuse the chroma directory chosen by coa_store.py for consistency.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DATA_ROOT = _BACKEND_ROOT / "data"
_DATA_ROOT.mkdir(exist_ok=True)
_CHROMA_DIR = _DATA_ROOT / "chroma"
_CHROMA_DIR.mkdir(exist_ok=True)

_SKILLS_ROOT = _BACKEND_ROOT / "skills" / "worker"
_COLLECTION = "kb_canon"

# ~500 tokens ≈ ~2000 characters (rule-of-thumb 4 chars/token for English).
_CHUNK_CHAR_LIMIT = 2000

_embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)
_chroma_client: Optional[chromadb.PersistentClient] = None


def _client() -> chromadb.PersistentClient:
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=str(_CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
    return _chroma_client


@dataclass
class KBHit:
    text: str
    citation: str
    score: float
    source_path: str
    denomination: str = ""
    section_heading: str = ""
    church_id: str = ""
    source_filename: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _denomination_from_dir(dir_name: str) -> str:
    # e.g. "denomination_episcopal" -> "EPISCOPAL"
    if dir_name.startswith("denomination_"):
        return dir_name[len("denomination_"):].upper()
    return dir_name.upper()


def _strip_frontmatter(md: str) -> str:
    if md.startswith("---"):
        # Skip YAML frontmatter delimited by --- ... ---
        end = md.find("\n---", 3)
        if end != -1:
            return md[end + 4:].lstrip()
    return md


def _chunk_markdown(md: str) -> List[Dict[str, str]]:
    """Split markdown by ## H2 headings; if a section exceeds the char limit,
    further break by paragraphs. Returns list of {section_heading, text}.
    """
    body = _strip_frontmatter(md)
    # Split on H2 headings (## ) — preserve heading text.
    parts = re.split(r"(?m)^(##\s+.+)$", body)
    chunks: List[Dict[str, str]] = []
    # parts looks like ["preamble", "## Heading 1", "body 1", "## Heading 2", "body 2", ...]
    if parts and parts[0].strip():
        chunks.append({"section_heading": "(intro)", "text": parts[0].strip()})
    i = 1
    while i < len(parts):
        heading = parts[i].strip().lstrip("#").strip()
        body_text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if body_text:
            # Sub-chunk if too long.
            if len(body_text) <= _CHUNK_CHAR_LIMIT:
                chunks.append({"section_heading": heading, "text": body_text})
            else:
                paragraphs = re.split(r"\n\s*\n", body_text)
                buf = ""
                idx = 0
                for p in paragraphs:
                    if len(buf) + len(p) + 2 > _CHUNK_CHAR_LIMIT and buf:
                        chunks.append({
                            "section_heading": f"{heading} (part {idx + 1})",
                            "text": buf.strip(),
                        })
                        idx += 1
                        buf = p
                    else:
                        buf = (buf + "\n\n" + p) if buf else p
                if buf.strip():
                    chunks.append({
                        "section_heading": f"{heading} (part {idx + 1})" if idx else heading,
                        "text": buf.strip(),
                    })
        i += 2
    return chunks


def _build_citation(denomination: str, section_heading: str) -> str:
    """Construct a short human-readable citation string.

    Uses the standard Episcopal canon shorthand "Title I, Canon 7" when the
    section heading mentions "Discretionary Fund" (per TEC Title I, Canon 7
    governing parish administration), falling back to a generic shorthand.
    """
    denom = (denomination or "").upper()
    heading_low = (section_heading or "").lower()

    if denom == "EPISCOPAL":
        if "discretionary" in heading_low:
            return "Title I, Canon 7 (TEC Discretionary Funds)"
        if "endowment" in heading_low:
            return "FASB ASC 958-205 (TEC Endowment)"
        if "diocesan" in heading_low or "assessment" in heading_low:
            return "TEC Diocesan Canon (Assessment)"
        if "rector" in heading_low or "clergy" in heading_low:
            return "TEC Title III (Clergy Compensation)"
        if "parochial" in heading_low:
            return "TEC Parochial Report Canon"
        return f"TEC Canon — {section_heading}"
    if denom == "UMC":
        return f"UMC Book of Discipline — {section_heading}"
    if denom == "PRESBYTERIAN_PCUSA":
        return f"PC(USA) Book of Order — {section_heading}"
    if denom == "CATHOLIC_PARISH":
        return f"Code of Canon Law — {section_heading}"
    if denom == "BAPTIST_INDEPENDENT":
        return f"Baptist Polity — {section_heading}"
    return f"{denom or 'Canon'} — {section_heading}"


def _collection_has_documents() -> bool:
    """Return True iff the kb_canon collection exists and is non-empty."""
    client = _client()
    try:
        coll = client.get_collection(_COLLECTION, embedding_function=_embed_fn)
    except Exception:
        return False
    try:
        return coll.count() > 0
    except Exception:
        return False


def ingest_canon_skills(force: bool = False) -> int:
    """Idempotently load all denomination_*/SKILL.md files into kb_canon.

    Returns the number of chunks ingested (0 if skipped because already populated).
    """
    if not force and _collection_has_documents():
        return 0

    client = _client()
    try:
        client.delete_collection(_COLLECTION)
    except Exception:
        pass
    coll = client.create_collection(
        name=_COLLECTION,
        embedding_function=_embed_fn,
        metadata={"description": "EIME canon knowledge base — denomination skills"},
    )

    docs: List[str] = []
    metas: List[Dict[str, Any]] = []
    ids: List[str] = []

    if not _SKILLS_ROOT.exists():
        return 0

    for skill_dir in sorted(_SKILLS_ROOT.iterdir()):
        if not skill_dir.is_dir():
            continue
        if not skill_dir.name.startswith("denomination_"):
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            md_text = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue
        denom = _denomination_from_dir(skill_dir.name)
        chunks = _chunk_markdown(md_text)
        for idx, ch in enumerate(chunks):
            chunk_id = f"{skill_dir.name}__{idx:03d}"
            docs.append(ch["text"])
            metas.append({
                "denomination": denom,
                "source_path": str(skill_md.relative_to(_BACKEND_ROOT.parent)),
                "section_heading": ch["section_heading"],
                "citation": _build_citation(denom, ch["section_heading"]),
            })
            ids.append(chunk_id)

    if docs:
        coll.add(documents=docs, metadatas=metas, ids=ids)
    return len(docs)


def _kb_search_canon(
    query: str,
    k: int = 3,
    denomination: Optional[str] = None,
) -> List[KBHit]:
    """Search ONLY the global canon collection (kb_canon)."""
    if not query or not query.strip():
        return []
    # Lazy ingestion: if the collection is empty, build it on first search.
    if not _collection_has_documents():
        try:
            ingest_canon_skills()
        except Exception:
            return []

    client = _client()
    try:
        coll = client.get_collection(_COLLECTION, embedding_function=_embed_fn)
    except Exception:
        return []

    where = None
    if denomination:
        where = {"denomination": denomination.upper()}

    try:
        res = coll.query(query_texts=[query], n_results=max(k, 1), where=where)
    except Exception:
        return []

    metas = (res.get("metadatas") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]
    documents = (res.get("documents") or [[]])[0]

    hits: List[KBHit] = []
    for meta, dist, doc in zip(metas, distances, documents):
        score = float(1.0 - min(dist, 1.0))
        hits.append(KBHit(
            text=doc or "",
            citation=str(meta.get("citation", "")),
            score=score,
            source_path=str(meta.get("source_path", "")),
            denomination=str(meta.get("denomination", "")),
            section_heading=str(meta.get("section_heading", "")),
        ))
    return hits


# =====================================================================
# Phase 2.9 — Per-church knowledge base
# =====================================================================

# Storage layout for uploaded source files:
#   backend/data/kb/{church_id}/{filename}
_KB_FILES_ROOT = _DATA_ROOT / "kb"


def _church_collection_name(church_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]", "_", church_id or "default")
    return f"kb_{safe}"


def _church_kb_dir(church_id: str) -> Path:
    d = _KB_FILES_ROOT / church_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_or_create_church_collection(church_id: str):
    client = _client()
    name = _church_collection_name(church_id)
    try:
        return client.get_collection(name, embedding_function=_embed_fn)
    except Exception:
        return client.create_collection(
            name=name,
            embedding_function=_embed_fn,
            metadata={"description": f"EIME per-church KB — {church_id}"},
        )


def _build_church_citation(filename: str, section_heading: str) -> str:
    """Generate a human-readable citation for a per-church KB chunk.

    e.g. "Parish Policy Manual, Section 4.2"
    """
    base = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    base_title = base.title() if base else "Document"
    if section_heading and section_heading != "(intro)":
        return f"{base_title}, {section_heading}"
    return base_title


def _delete_chunks_for_file(church_id: str, filename: str) -> int:
    """Remove all chunks whose metadata.filename == filename. Returns count."""
    coll = _get_or_create_church_collection(church_id)
    try:
        existing = coll.get(where={"filename": filename})
    except Exception:
        return 0
    ids = existing.get("ids") or []
    if not ids:
        return 0
    try:
        coll.delete(ids=ids)
    except Exception:
        return 0
    return len(ids)


def ingest_church_kb(church_id: str, file_path: Path) -> int:
    """Idempotently ingest a single uploaded file into kb_{church_id}.

    Re-ingesting the same filename replaces (does not duplicate) prior chunks.

    Args:
        church_id: church identifier.
        file_path: Path to the file (PDF / MD / TXT) on disk.

    Returns:
        Number of chunks ingested for this file.
    """
    from .file_text_extractor import extract_text as _extract

    p = Path(file_path)
    if not p.exists():
        return 0

    text = _extract(p)
    if not text or not text.strip():
        return 0

    # Idempotent replace: drop prior chunks for this filename.
    _delete_chunks_for_file(church_id, p.name)

    chunks = _chunk_markdown(text) if p.suffix.lower() in {".md", ".markdown"} \
        else _chunk_plain_text(text)

    if not chunks:
        return 0

    coll = _get_or_create_church_collection(church_id)
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []
    ids: List[str] = []
    for idx, ch in enumerate(chunks):
        chunk_id = f"{church_id}__{p.name}__{idx:04d}"
        section_heading = ch.get("section_heading", "")
        docs.append(ch["text"])
        metas.append({
            "church_id": church_id,
            "filename": p.name,
            "source_path": str(p),
            "section_heading": section_heading,
            "citation": _build_church_citation(p.name, section_heading),
        })
        ids.append(chunk_id)

    coll.add(documents=docs, metadatas=metas, ids=ids)
    return len(docs)


def _chunk_plain_text(text: str) -> List[Dict[str, str]]:
    """Chunk a non-markdown text by paragraphs into ~_CHUNK_CHAR_LIMIT pieces."""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chunks: List[Dict[str, str]] = []
    buf = ""
    idx = 0
    for p in paragraphs:
        if len(buf) + len(p) + 2 > _CHUNK_CHAR_LIMIT and buf:
            chunks.append({
                "section_heading": f"Section {idx + 1}",
                "text": buf.strip(),
            })
            idx += 1
            buf = p
        else:
            buf = (buf + "\n\n" + p) if buf else p
    if buf.strip():
        chunks.append({
            "section_heading": f"Section {idx + 1}" if idx else "(intro)",
            "text": buf.strip(),
        })
    return chunks


def list_church_kb_files(church_id: str) -> List[Dict[str, Any]]:
    """Return uploaded files in the church's KB directory + chunk count."""
    d = _church_kb_dir(church_id)
    out: List[Dict[str, Any]] = []
    coll = None
    try:
        coll = _get_or_create_church_collection(church_id)
    except Exception:
        coll = None
    for fp in sorted(d.iterdir()):
        if not fp.is_file():
            continue
        chunk_count = 0
        if coll is not None:
            try:
                got = coll.get(where={"filename": fp.name})
                chunk_count = len(got.get("ids") or [])
            except Exception:
                chunk_count = 0
        out.append({
            "filename": fp.name,
            "size_bytes": fp.stat().st_size,
            "chunk_count": chunk_count,
        })
    return out


def delete_church_kb_file(church_id: str, filename: str) -> bool:
    """Remove a file from disk + delete its chunks. Returns True iff removed."""
    d = _church_kb_dir(church_id)
    fp = d / filename
    if not fp.exists() or not fp.is_file():
        # still try to clean stray chunks even if file missing
        _delete_chunks_for_file(church_id, filename)
        return False
    _delete_chunks_for_file(church_id, filename)
    try:
        fp.unlink()
    except Exception:
        return False
    return True


def kb_search_church(query: str, church_id: str, k: int = 3) -> List[KBHit]:
    """Search ONLY the church's per-church KB collection."""
    if not query or not query.strip() or not church_id:
        return []
    client = _client()
    name = _church_collection_name(church_id)
    try:
        coll = client.get_collection(name, embedding_function=_embed_fn)
    except Exception:
        return []
    try:
        res = coll.query(query_texts=[query], n_results=max(k, 1))
    except Exception:
        return []
    metas = (res.get("metadatas") or [[]])[0]
    distances = (res.get("distances") or [[]])[0]
    documents = (res.get("documents") or [[]])[0]

    hits: List[KBHit] = []
    for meta, dist, doc in zip(metas, distances, documents):
        score = float(1.0 - min(dist, 1.0))
        hits.append(KBHit(
            text=doc or "",
            citation=str(meta.get("citation", "")),
            score=score,
            source_path=str(meta.get("source_path", "")),
            denomination="",
            section_heading=str(meta.get("section_heading", "")),
            church_id=str(meta.get("church_id", church_id)),
            source_filename=str(meta.get("filename", "")),
        ))
    return hits


def kb_search(
    query: str,
    church_id: Optional[str] = None,
    k: int = 3,
    denomination: Optional[str] = None,
) -> List[KBHit]:
    """Combined KB search: queries `kb_canon` AND, when supplied, the church
    collection `kb_{church_id}`. Hits are merged and re-ranked by score
    (highest first), capped at `k`.

    Args:
        query: free-text search query.
        church_id: optional church id for per-church augmentation.
        k: number of total hits to return.
        denomination: optional denomination filter for the canon collection.
    """
    canon_hits = _kb_search_canon(query, k=k, denomination=denomination)
    church_hits: List[KBHit] = []
    if church_id:
        church_hits = kb_search_church(query, church_id=church_id, k=k)
    merged = canon_hits + church_hits
    merged.sort(key=lambda h: h.score, reverse=True)
    return merged[:k]
