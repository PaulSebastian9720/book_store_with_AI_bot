import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.persistence.db import init_db, async_session
from app.persistence.seed import seed_database
from app.api.routes import router as api_router
from app.api.ws import router as ws_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def init_neo4j_graph():
    """Inicializa el grafo de estados en Neo4j."""
    from neo4j import AsyncGraphDatabase

    try:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

        states = [
            ("VALIDATE_INPUT", "Valida datos de entrada del usuario"),
            ("LOAD_CONTEXT", "Carga contexto desde la base de datos"),
            ("APPLY_ACTION", "Ejecuta la acción semántica seleccionada"),
            ("PERSIST", "Persiste cambios en la base de datos"),
            ("BUILD_RESPONSE", "Construye respuesta natural con LLM"),
            ("DONE", "Estado terminal - flujo completado"),
            ("ASK_INPUT", "Solicita datos faltantes al usuario"),
        ]

        transitions = [
            ("VALIDATE_INPUT", "LOAD_CONTEXT", "valid_input"),
            ("VALIDATE_INPUT", "ASK_INPUT", "missing_data"),
            ("ASK_INPUT", "VALIDATE_INPUT", "user_responded"),
            ("LOAD_CONTEXT", "APPLY_ACTION", "context_loaded"),
            ("APPLY_ACTION", "PERSIST", "action_completed"),
            ("APPLY_ACTION", "BUILD_RESPONSE", "action_failed"),
            ("PERSIST", "BUILD_RESPONSE", "persisted"),
            ("BUILD_RESPONSE", "DONE", "response_built"),
        ]

        async with driver.session() as neo_session:
            # Clear existing graph
            await neo_session.run("MATCH (n:State) DETACH DELETE n")

            # Create states
            for name, description in states:
                await neo_session.run(
                    "CREATE (:State {name: $name, description: $description})",
                    name=name, description=description,
                )

            # Create transitions
            for from_state, to_state, condition in transitions:
                await neo_session.run(
                    """
                    MATCH (a:State {name: $from_state})
                    MATCH (b:State {name: $to_state})
                    CREATE (a)-[:TRANSITION {condition: $condition}]->(b)
                    """,
                    from_state=from_state, to_state=to_state, condition=condition,
                )

        await driver.close()
        logger.info("Grafo de estados inicializado en Neo4j correctamente")

    except Exception as e:
        logger.warning("No se pudo conectar a Neo4j (se reintentará): %s", str(e))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Iniciando Bookstore Semantic Orchestrator...")

    # Init database
    await init_db()
    logger.info("Base de datos inicializada")

    # Seed data
    async with async_session() as session:
        await seed_database(session)

    # Init Neo4j graph
    await init_neo4j_graph()

    logger.info("Sistema listo para recibir consultas")
    yield
    logger.info("Apagando el sistema...")


app = FastAPI(
    title="Bookstore Semantic Orchestrator",
    description="Backend académico con embeddings, LangGraph y orquestador semántico",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ws_router)


@app.get("/")
async def root():
    return {
        "name": "Bookstore Semantic Orchestrator",
        "version": "1.0.0",
        "endpoints": {
            "websocket": "/ws/chat?user_id=1",
            "books": "/books",
            "cart": "/cart?user_id=1",
            "orders": "/orders?user_id=1",
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
