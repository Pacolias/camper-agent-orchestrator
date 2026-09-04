from langchain_google_genai import ChatGoogleGenerativeAI
from pathlib import Path
from app.core.config import settings
from app.agents.state import RouteState

llm = ChatGoogleGenerativeAI(
    model="gemini-3.6-flash",
    api_key=settings.GEMINI_API_KEY,
    temperature=0.2
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = BASE_DIR / "prompts" / "route.txt"

with open(PROMPT_PATH, "r", encoding="utf-8") as f:
    PROMPT = f.read()

def supervisor_node(state: RouteState):
    user_request = state.get("user_request", "")

    response = llm.invoke([
        ("system", PROMPT),
        ("human", user_request)
    ])

    final_text = response.content 

    return {
        "final_itinerary": {"draft_route": final_text}
    }