import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

def run_ingestion():
    pdf_path = BASE_DIR / "data" / "ley_costas_y_pernocta.pdf"
    db_path = BASE_DIR / "chroma_db"

    if not pdf_path.exists():
        print(f"Error: There are no PDFs in {pdf_path}")
        return

    # Load PDF document
    loader = PyPDFLoader(str(pdf_path))
    docs = loader.load()

    # Chunk splitting
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = text_splitter.split_documents(docs)

    # Embeddings generation and save into ChromaDB
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(db_path)
    )

if __name__ == "__main__":
    run_ingestion()