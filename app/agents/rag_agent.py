from app.agents.state import RouteState

def rag_agent_node(state: RouteState):
    """
    Retrieve legal context for motorhome and campervan pernoctation 
    based on the destination provided in the RouteState.
    """
    destination = state.get("destination", "")

    # embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    # vector_store = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)
    # docs = vector_store.similarity_search(
    #     f"Motorhome and campervan pernoctation normative un {destination}"
    #     k=3
    # )
    # legal_context = "\n".join([doc.page_content for doc in docs])

    # Development mock
    legal_context = (
        f"Legal context for {destination}: parking allowed "
        "respecting the vehicle perimeter. It's forbidden to deploy "
        "elements like awnings or chairs in the public thoroughfare (Traffic Law)."
    )

    return {"legal_context" : legal_context}