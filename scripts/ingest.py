import shutil
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# The source PDF is organized by comunidad autónoma (long runs of enumerated
# regional decrees). A small chunk_size risks cutting a chunk mid-region, so
# the top similarity hit for one destination can come back describing an
# unrelated region. 1500/300 keeps most per-region passages intact in a
# single chunk, and the heavier overlap reduces the chance that the one
# sentence naming the region gets split away from the rules that follow it.
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 300

def run_ingestion():
    pdf_path = BASE_DIR / "data" / "ley_costas_y_pernocta.pdf"
    db_path = BASE_DIR / "chroma_db"

    if not pdf_path.exists():
        print(f"Error: There are no PDFs in {pdf_path}")
        return

    # Rebuild from scratch each run — Chroma.from_documents() appends to an
    # existing persisted collection rather than replacing it, so re-running
    # ingestion without clearing first would duplicate chunks and mix
    # different chunk_size generations in the same store.
    if db_path.exists():
        shutil.rmtree(db_path)

    # Load PDF document
    loader = PyPDFLoader(str(pdf_path))
    docs = loader.load()

    # Chunk splitting
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = text_splitter.split_documents(docs)

    # Embeddings generation and save into ChromaDB
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(db_path)
    )
    print(f"Ingested {len(chunks)} chunks (chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}) into {db_path}")

if __name__ == "__main__":
    run_ingestion()