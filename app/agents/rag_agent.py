from app.agents.state import RouteState
from app.core.config import settings
from langchain_huggingface import HuggingFaceEmbeddings

def rag_agent_node(state: RouteState):
    """
    Retrieve legal context for motorhome and campervan pernoctation 
    based on the destination provided in the RouteState.
    """
    destination = state.get("destination", "")

    try:
        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

        vector_store = Chroma(
            persist_directory="./chroma_db", 
            embedding_function=embeddings
        )

        docs = vector_store.similarity_search(
            f"Motorhome and campervan pernoctation normative in {destination}"
            k=3
        )

        if docs:
            legal_context = "\n".join([doc.page_content for doc in docs])
        else:
            raise ValueError("No coincidences in the data base.")

    except Exception as e:
        legal_context = (
            f"Legal context for {destination} (Fallback): parking allowed "
            "respecting the vehicle perimeter. It's forbidden to deploy "
            "elements like awnings or chairs in the public thoroughfare (Traffic Law)."
        )

    return {"legal_context": legal_context}