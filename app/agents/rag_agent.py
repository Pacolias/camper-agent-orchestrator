from pathlib import Path

import requests
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from app.agents.state import RouteState

CHROMA_DIR = Path(__file__).resolve().parent.parent.parent / "chroma_db"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "camper-agent-orchestrator/1.0"
REQUEST_TIMEOUT = 10

# See the matching comment in math_agent.py: bounding the search to Iberia
# avoids ambiguous place names (e.g. "Sagres" also exists in Brazil)
# resolving to the wrong country's region.
IBERIA_VIEWBOX = "-9.6,44.0,3.5,35.9"


def _get_region(place: str) -> str | None:
    """
    Best-effort lookup of the administrative region (comunidad autónoma /
    distrito) a place belongs to, used only to sharpen the RAG query text.

    This is NOT the "no silent fallbacks" retrieval path — it's an optional
    relevance hint on top of it. If Nominatim is unreachable we still run a
    REAL similarity search below, just keyed on the destination name alone
    instead of "destination, region". A network hiccup here must not take
    down legal-context retrieval, which is why only network errors are
    caught (not a broad except, and not swallowing the ChromaDB search).
    """
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={
                "q": place, "format": "json", "limit": 1, "addressdetails": 1,
                "viewbox": IBERIA_VIEWBOX, "bounded": 1
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        results = response.json()
    except requests.RequestException:
        return None

    if not results:
        return None

    address = results[0].get("address", {})
    return address.get("state") or address.get("region") or address.get("county")


def rag_agent_node(state: RouteState):
    """
    Retrieve legal context for motorhome and campervan pernoctation
    based on the destination provided in the RouteState.
    """
    destination = state.get("destination", "")

    if not CHROMA_DIR.exists():
        raise FileNotFoundError(
            f"ChromaDB not found at {CHROMA_DIR}. Run `python scripts/ingest.py` to build it "
            "before serving legal-context requests."
        )

    region = _get_region(destination)
    query = f"Motorhome and campervan pernoctation normative in {destination}"
    if region:
        query += f", region: {region}"

    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_store = Chroma(persist_directory=str(CHROMA_DIR), embedding_function=embeddings)

    docs = vector_store.similarity_search(query, k=3)

    if not docs:
        raise ValueError(f"No legal context found in ChromaDB for destination '{destination}'.")

    legal_context = "\n".join(doc.page_content for doc in docs)
    return {"legal_context": legal_context}