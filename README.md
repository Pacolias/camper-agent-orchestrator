# Camper Agent Orchestrator

![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi&logoColor=white)
![Uvicorn](https://img.shields.io/badge/Uvicorn-2094f3?style=for-the-badge&logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-1C3C3C?style=for-the-badge&logo=chainlink&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-4CAF50?style=for-the-badge&logo=graphql&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white)

A backend application that implements a Hub-and-Spoke multi-agent architecture for campervan route planning. Built with FastAPI and LangGraph, the system orchestrates a central supervisor LLM that dynamically delegates tasks to specialized sub-agents to resolve legal constraints, locate points of interest, and optimize fuel costs.

## How it works
The orchestration loop relies on a shared `RouteState`. The Supervisor agent evaluates the state at each iteration and routes execution to the corresponding tool until all required data is populated.

```mermaid
flowchart TD
    %% Estilos
    classDef api fill:#005571,stroke:#fff,stroke-width:2px,color:#fff;
    classDef agent fill:#8E75B2,stroke:#fff,stroke-width:2px,color:#fff;
    classDef supervisor fill:#FF4F00,stroke:#fff,stroke-width:2px,color:#fff;
    classDef tools fill:#3670A0,stroke:#fff,stroke-width:2px,color:#fff;
    classDef state fill:#4CAF50,stroke:#fff,stroke-width:2px,color:#fff;

    %% Nodos de entrada
    Client([Usuario / Frontend])
    Endpoint[FastAPI: POST /api/plan-route]:::api
    
    %% Grafo y Estado
    State[(RouteState: Memoria Compartida)]:::state
    
    %% Agentes (Nodos de LangGraph)
    Supervisor{Supervisor Agent}:::supervisor
    RagAgent[RAG Legal Agent]:::agent
    SqlAgent[SQL POI Agent]:::agent
    MathAgent[Math Optimization Agent]:::agent
    
    %% Herramientas
    Chroma[(ChromaDB\nNormativas PDF)]:::tools
    SQLDB[(SQLite/MySQL\nÁreas Camper)]:::tools
    SciPy[NumPy/SciPy\nCálculo Desnivel]:::tools

    %% Flujo de ejecución
    Client -- "Petición en lenguaje natural" --> Endpoint
    Endpoint -- "Inicializa" --> State
    State -- "Pasa el estado al punto de entrada" --> Supervisor
    
    %% Enrutamiento Cíclico
    Supervisor -- "Falta contexto normativo" --> RagAgent
    Supervisor -- "Faltan áreas/precios" --> SqlAgent
    Supervisor -- "Falta cálculo de consumo" --> MathAgent
    
    %% Uso de herramientas
    RagAgent -. "Búsqueda Semántica" .-> Chroma
    SqlAgent -. "Consultas SQL (MCP)" .-> SQLDB
    MathAgent -. "Algoritmos" .-> SciPy
    
    %% Retorno al estado y supervisor (El bucle de LangGraph)
    RagAgent -- "Actualiza RouteState" --> Supervisor
    SqlAgent -- "Actualiza RouteState" --> Supervisor
    MathAgent -- "Actualiza RouteState" --> Supervisor
    
    %% Salida
    Supervisor -- "Estado completo" --> Final[Genera JSON Estructurado]
    Final -- "Devuelve 200 OK" --> Endpoint
    Endpoint --> Client
```

## Core Components

- **Supervisor Agent**: The central decision-maker. It relies on a deterministic prompt and Pydantic structured outputs to evaluate the RouteState missing fields and trigger conditional routing.

- **SQL POI Agent**: Interfaces with a relational database to fetch viable overnight parking locations matching user constraints (e.g., electricity hookups).

- **RAG Legal Agent**: Uses semantic search over a vector store to retrieve local regulations regarding campervan parking and overnight stays for the targeted regions.

- **Math Agent**: Handles numerical processing for fuel cost estimations and driving time optimizations based on distance and vehicle consumption.

## Local Setup

1. Clone the repository and navigate to the project root.
2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate

```

3. Install dependencies:
```bash
pip install -r requirements.txt

```

4. Set up environment variables. Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_api_key_here

```

5. Run the development server:
```bash
python -m uvicorn app.main:app --reload

```

## Usage
Send a POST request to the API to trigger the graph execution. The graph will loop until the Supervisor resolves all missing data and compiles the final itinerary.

```bash
curl -X POST "http://localhost:8000/api/route" \
     -H "Content-Type: application/json" \
     -d '{
           "origin": "Málaga",
           "destination": "Sagres",
           "max_driving_hours_per_day": 4,
           "requires_hookups": true,
           "preferences": ["coastal"]
         }'

```

## Copyright and License
This project is open-source software licensed under the MIT License.
