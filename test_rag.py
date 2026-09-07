"""
Manual isolation test for the RAG pipeline. Bypasses rag_agent_node entirely
and queries ChromaDB directly, filtered by metadata, to determine whether a
region-retrieval problem lives in the database/metadata layer or in the
agent's region-resolution logic sitting on top of it.

Usage: python test_rag.py
"""
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

CHROMA_DIR = "./chroma_db"


def main():
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_store = Chroma(persist_directory=CHROMA_DIR, embedding_function=embeddings)

    # 1. Raw collection dump: what regions actually exist as metadata?
    raw = vector_store._collection.get(include=["metadatas"])
    from collections import Counter
    region_counts = Counter(m.get("region") for m in raw["metadatas"])
    print("=== Regions present in ChromaDB metadata ===")
    for region, count in sorted(region_counts.items()):
        print(f"  {region!r}: {count} chunk(s)")
    print()

    # 2. Manual filtered query: does filter={"region": "Andalucía"} return anything?
    print("=== similarity_search(..., filter={'region': 'Andalucía'}) ===")
    docs = vector_store.similarity_search(
        "Motorhome and campervan pernoctation normative in Málaga",
        k=3,
        filter={"region": "Andalucía"}
    )
    print(f"{len(docs)} doc(s) returned")
    for d in docs:
        print(f"  metadata={d.metadata} | content[:120]={d.page_content[:120]!r}")
    print()

    # 3. Same query with NO filter, for comparison.
    print("=== similarity_search(..., no filter) ===")
    docs_unfiltered = vector_store.similarity_search(
        "Motorhome and campervan pernoctation normative in Málaga", k=3
    )
    for d in docs_unfiltered:
        print(f"  metadata={d.metadata} | content[:120]={d.page_content[:120]!r}")
    print()

    # 4. Sanity check: filtering by a region that should return ZERO results.
    print("=== similarity_search(..., filter={'region': 'Nonexistent'}) ===")
    docs_empty = vector_store.similarity_search(
        "anything", k=3, filter={"region": "Nonexistent"}
    )
    print(f"{len(docs_empty)} doc(s) returned (expected 0)")


if __name__ == "__main__":
    main()
