import logging
from pathlib import Path

import requests
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from app.agents.state import RouteState

logger = logging.getLogger(__name__)

CHROMA_DIR = Path(__file__).resolve().parent.parent.parent / "chroma_db"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "camper-agent-orchestrator/1.0"
REQUEST_TIMEOUT = 10

# See the matching comment in math_agent.py: bounding the search to Iberia
# avoids ambiguous place names (e.g. "Sagres" also exists in Brazil)
# resolving to the wrong country's region.
IBERIA_VIEWBOX = "-9.6,44.0,3.5,35.9"

GENERAL_TAG = "general"

# Must match the region tags scripts/ingest.py assigns to chunk metadata
# (REGION_HEADER_RE there). Nominatim/OSM names a region differently from
# how the legal document itself names it (e.g. "Euskadi" vs. "País Vasco",
# "Comunitat Valenciana" vs. "Valencia") — an exact metadata `filter` needs
# this alias table, or a real, covered region silently matches zero chunks.
REGION_ALIASES = {
    "andalucía": "Andalucía", "andalucia": "Andalucía",
    "país vasco": "País Vasco", "pais vasco": "País Vasco", "euskadi": "País Vasco",
    "castilla y león": "Castilla y León", "castilla y leon": "Castilla y León",
    "castilla-la mancha": "Castilla-La Mancha", "castilla la mancha": "Castilla-La Mancha",
    "cantabria": "Cantabria",
    "galicia": "Galicia",
    "cataluña": "Cataluña", "catalunya": "Cataluña", "cataluna": "Cataluña",
    "comunidad valenciana": "Valencia", "comunitat valenciana": "Valencia",
    "valencia": "Valencia", "comunidad de valencia": "Valencia",
    "asturias": "Asturias", "principado de asturias": "Asturias",
    "murcia": "Murcia", "región de murcia": "Murcia", "region de murcia": "Murcia",
    "aragón": "Aragón", "aragon": "Aragón",
    "navarra": "Navarra", "comunidad foral de navarra": "Navarra", "nafarroa": "Navarra",
    "madrid": "Madrid", "comunidad de madrid": "Madrid",
    "extremadura": "Extremadura",
}


# Query Expansion / Entity Resolution: the app's destinations are cities
# ("Málaga", "Sagres"), but the legal document is organized by comunidad
# autónoma — a city name alone is the wrong granularity for the metadata
# filter and has to be expanded to its macro-region first. This static
# table is the PRIMARY resolution path (checked before any network call):
# it's deterministic, has zero latency, and cannot be silently degraded by
# Nominatim rate-limiting the way a live geocode lookup can (observed in
# testing: a live geocode per leg, multiplied by 2 legs after a split, was
# occasionally throttled, and _get_region's narrow exception handling then
# correctly-but-unhelpfully returned None instead of crashing the request —
# "region: null" traced back to Nominatim's ~1 req/s policy, not the join
# logic). One entry per destination actually seeded in scripts/seed_poi_db.py
# (kept in sync with it), mapped to the exact tag scripts/ingest.py uses.
# Spanish destinations map to their comunidad autónoma; Portuguese ones map
# to None deliberately — this document has no Portugal-specific content, so
# claiming e.g. "Algarve" as a region here would just be a filter that can
# never match anything. `_get_region`/`_canonical_region` (live Nominatim
# geocoding) remain as a best-effort fallback for any destination NOT in
# this table, so an arbitrary/unseen Spanish city still gets a real attempt
# at resolution instead of always falling back to "general".
DESTINATION_REGION_MAP: dict[str, str | None] = {
    # Andalucía
    "málaga": "Andalucía", "cádiz": "Andalucía", "conil de la frontera": "Andalucía",
    "zahara de los atunes": "Andalucía", "marbella": "Andalucía", "nerja": "Andalucía",
    "huelva": "Andalucía", "sevilla": "Andalucía", "granada": "Andalucía",
    "almería": "Andalucía", "cabo de gata": "Andalucía", "tarifa": "Andalucía",
    # Cataluña
    "barcelona": "Cataluña", "tarragona": "Cataluña", "girona": "Cataluña", "roses": "Cataluña",
    # Valencia
    "valencia": "Valencia", "alicante": "Valencia", "castellón": "Valencia", "peñíscola": "Valencia",
    # País Vasco
    "san sebastián": "País Vasco", "bilbao": "País Vasco", "zarautz": "País Vasco",
    # Cantabria
    "santander": "Cantabria",
    # Galicia
    "a coruña": "Galicia", "vigo": "Galicia", "pontevedra": "Galicia",
    # Asturias
    "gijón": "Asturias", "llanes": "Asturias",
    # Murcia
    "cartagena": "Murcia", "águilas": "Murcia", "murcia": "Murcia",
    # Madrid
    "madrid": "Madrid", "alcalá de henares": "Madrid",
    # Portugal — no region-specific content in this document, see docstring above.
    "sagres": None, "lagos": None, "faro": None, "albufeira": None, "tavira": None,
    "lisboa": None, "porto": None, "peniche": None, "cascais": None, "ericeira": None,
    "vila nova de milfontes": None, "figueira da foz": None, "viana do castelo": None,
}


def _resolve_region(destination: str) -> str | None:
    """
    Query Expansion step: city -> macro-region (comunidad autónoma), the
    granularity the legal document and its chunk metadata actually use.
    Static map first (deterministic, no network); live geocoding fallback
    for anything not in it.
    """
    mapped = DESTINATION_REGION_MAP.get(destination.strip().lower(), "__not_found__")
    if mapped != "__not_found__":
        return mapped
    return _canonical_region(_get_region(destination))


def _get_region(place: str) -> str | None:
    """
    Best-effort lookup of the raw administrative region name Nominatim
    reports for a place — canonicalized separately by `_canonical_region`.

    This is NOT the "no silent fallbacks" retrieval path — it's an optional
    input to the metadata filter below. If Nominatim is unreachable we still
    run a REAL, filtered similarity search below, just filtered to
    GENERAL_TAG instead of a specific region. A network hiccup here must not
    take down legal-context retrieval, which is why only network errors are
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


def _canonical_region(raw_region: str | None) -> str | None:
    """Map Nominatim's region name to the tag scripts/ingest.py stored in chunk metadata."""
    if not raw_region:
        return None
    return REGION_ALIASES.get(raw_region.strip().lower())


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

    resolved = _resolve_region(destination)
    logger.debug("rag_agent_node: destination=%r resolved_region=%r", destination, resolved)
    region = resolved or GENERAL_TAG

    # De-dup across legs: a multi-leg trip that revisits the same region
    # (e.g. two legs both within Andalucía) must not re-query ChromaDB or
    # store the same block of legal text twice. legal_context_by_region is
    # the single source of truth per region for the whole route.
    # state["legal_context"]/state["legal_region"] still get set for the
    # CURRENT leg so downstream code is unaffected — they're just backed by
    # the cache instead of a fresh query on a repeat.
    cache = dict(state.get("legal_context_by_region") or {})
    if region in cache:
        return {"legal_context": cache[region], "legal_region": region, "legal_context_by_region": cache}

    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    vector_store = Chroma(persist_directory=str(CHROMA_DIR), embedding_function=embeddings)

    query = f"Motorhome and campervan pernoctation normative in {destination}"

    # Hybrid retrieval: metadata `filter` is a HARD constraint that narrows
    # the search space to the destination's actual region before embeddings
    # rank relevance within it — this (not a query-text hint) is what fixes
    # geographic blindness. The region-specific chunk is queried separately
    # from "general" so it can't get crowded out purely on embedding
    # similarity by the much larger pool of general/preamble chunks.
    docs = []
    if region != GENERAL_TAG:
        docs += vector_store.similarity_search(query, k=2, filter={"region": region})
    if len(docs) < 3:
        docs += vector_store.similarity_search(query, k=3 - len(docs), filter={"region": GENERAL_TAG})

    if not docs:
        raise ValueError(f"No legal context found in ChromaDB for destination '{destination}'.")

    legal_context = "\n".join(doc.page_content for doc in docs)
    cache[region] = legal_context
    return {"legal_context": legal_context, "legal_region": region, "legal_context_by_region": cache}