import re
import shutil
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 300

GENERAL_TAG = "general"

# PyPDFLoader extracts this digital-signature validation stamp (URL + CSV +
# signer name) from every page's header/footer and splices it directly into
# the middle of the flowing text — not as a clean paragraph, mid-sentence.
# Left in place it (a) pollutes the embedding of whatever chunk it lands in
# with irrelevant signature boilerplate, and (b) surfaces as literal noise
# in legal_context ("...INFORME DE FIRMA... FIRMANTE(1): PERE NAVARRO
# OLIVELLA..."). It repeats verbatim ~16 times (found by inspecting the
# actual extracted text) and must be stripped before region-splitting, or
# the region-boundary regexes below could themselves land inside a stamp.
SIGNATURE_STAMP_RE = re.compile(r'https://run\.gob\.es/\S+.*?Sin acción específica\s*', re.DOTALL)

# The source PDF enumerates region-specific motorhome/camping decrees as a
# fixed sequence of "En <region> el Decreto/Ley ..." paragraphs. This list
# and order were extracted from the actual document text (see CLAUDE.md for
# how), not guessed from Spain's full list of comunidades autónomas — this
# PDF only covers these 14 (no Baleares/Canarias/La Rioja/Ceuta/Melilla). If
# the source PDF is ever replaced, re-derive this list before trusting it.
REGION_HEADER_RE = re.compile(
    r'\nEn (?:el |la |los |las )?'
    r'(País Vasco|Castilla y León|Andalucía|Castilla-La Mancha|Cantabria|'
    r'Galicia|Cataluña|Valencia|Asturias|Murcia|Aragón|Navarra|Madrid|Extremadura)\b'
)

# The regional enumeration lives entirely inside subsection "7.1 – Normativas
# autonómicas", which ends where "7.2 – Comunicación de datos" begins. This
# bound matters: an earlier version of this script assumed "everything after
# the last region match belongs to that region", which silently swallowed
# the unrelated 7.2 section (national data-reporting rules, nothing to do
# with any specific region) into Extremadura's tag. Anchoring on the
# document's own subsection headers instead of "last match wins" avoids that
# class of bug entirely.
REGIONAL_SECTION_START_RE = re.compile(r'\n7\.1\s*[–-]\s*Normativas autonómicas')
REGIONAL_SECTION_END_RE = re.compile(r'\n7\.2\s*[–-]')


def _split_by_region(full_text: str) -> list[tuple[str, str]]:
    """
    Cut the raw document text at each region-header boundary BEFORE running
    the recursive chunker, instead of chunking first and inferring a chunk's
    region afterward. Chunking first is what let a single chunk straddle two
    regions and get tagged by whichever text happened to dominate — the
    root cause of the RAG agent returning e.g. País Vasco content for an
    Andalucía route. Splitting on the actual paragraph boundaries first
    guarantees every chunk descends from exactly one region's segment.

    Only text inside the "7.1 – Normativas autonómicas" subsection is
    eligible to be tagged by region; everything else (definitions, traffic
    law framing, the unrelated "7.2 – Comunicación de datos" section, etc.)
    is tagged "general" — national-level content that applies regardless of
    destination.

    Returns [(region_or_general_tag, segment_text), ...] in document order.
    """
    start_m = REGIONAL_SECTION_START_RE.search(full_text)
    if not start_m:
        return [(GENERAL_TAG, full_text)]

    end_m = REGIONAL_SECTION_END_RE.search(full_text, pos=start_m.end())
    regional_start, regional_end = start_m.start(), (end_m.start() if end_m else len(full_text))
    regional_text = full_text[regional_start:regional_end]

    segments = [(GENERAL_TAG, full_text[:regional_start])]

    matches = list(REGION_HEADER_RE.finditer(regional_text))
    if matches:
        segments.append((GENERAL_TAG, regional_text[:matches[0].start()]))
        for i, m in enumerate(matches):
            seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(regional_text)
            segments.append((m.group(1), regional_text[m.start():seg_end]))
    else:
        segments.append((GENERAL_TAG, regional_text))

    segments.append((GENERAL_TAG, full_text[regional_end:]))

    return [(tag, text) for tag, text in segments if text.strip()]


def run_ingestion():
    pdf_path = BASE_DIR / "data" / "ley_costas_y_pernocta.pdf"
    db_path = BASE_DIR / "chroma_db"

    if not pdf_path.exists():
        print(f"Error: There are no PDFs in {pdf_path}")
        return

    # Rebuild from scratch each run — Chroma.from_documents() appends to an
    # existing persisted collection rather than replacing it, so re-running
    # ingestion without clearing first would duplicate chunks and mix
    # different chunk_size/tagging generations in the same store.
    if db_path.exists():
        shutil.rmtree(db_path)

    loader = PyPDFLoader(str(pdf_path))
    pages = loader.load()
    full_text = "\n".join(page.page_content for page in pages)

    cleaned_text, n_stamps = SIGNATURE_STAMP_RE.subn(" ", full_text)
    print(f"Stripped {n_stamps} signature-stamp occurrences ({len(full_text) - len(cleaned_text)} chars)")
    full_text = cleaned_text

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

    chunks: list[Document] = []
    region_counts: dict[str, int] = {}
    for region, segment_text in _split_by_region(full_text):
        pieces = text_splitter.split_text(segment_text)
        chunks.extend(Document(page_content=piece, metadata={"region": region}) for piece in pieces)
        region_counts[region] = region_counts.get(region, 0) + len(pieces)

    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(db_path)
    )
    print(f"Ingested {len(chunks)} chunks (chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}) into {db_path}")
    print(f"Chunks per region: {region_counts}")

if __name__ == "__main__":
    run_ingestion()