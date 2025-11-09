from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging

from app.config import settings
from app.database import engine, create_tables
from app.models import Base
from app.api import auth, user, translation

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Lifespan events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: criar tabelas do banco
    logger.info("Criando tabelas do banco de dados...")
    create_tables()
    logger.info("Tabelas criadas com sucesso!")
    
    yield
    
    # Shutdown: fechar conexões
    logger.info("Encerrando aplicação...")

# Configuração da aplicação FastAPI
app = FastAPI(
    title="BookAI - Tradutor de Livros com IA",
    version="1.0.0",
    description="API para tradução de livros completos usando DeepL",
    lifespan=lifespan
)

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Erro não tratado: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Erro interno do servidor"}
    )

# Include routers
app.include_router(auth.router)
app.include_router(user.router)
app.include_router(translation.router)

# Root endpoints
@app.get("/")
async def root():
    return {
        "message": "BookAI API",
        "version": "1.0.0",
        "status": "online"
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
