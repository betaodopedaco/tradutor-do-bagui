import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models import User
from app.schemas.user import UserCreate, UserLogin, UserResponse, Token
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_token,
    generate_referral_code,
    TokenError
)
from app.utils.dependencies import get_current_active_user
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    """
    Registrar novo usuário
    
    - Verifica se email já existe
    - Hash da senha com bcrypt
    - Cria usuário com 50.000 créditos grátis
    - Gera código de referral único
    - Se forneceu referral_code, credita 100k para quem indicou
    - Retorna dados do usuário (sem senha)
    """
    try:
        # Verificar se email já existe
        existing_user = db.query(User).filter(User.email == user_data.email).first()
        
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email já cadastrado"
            )
        
        # Hash da senha
        password_hash = hash_password(user_data.password)
        
        # Gerar código de referral
        referral_code = generate_referral_code(user_data.email)
        
        # Verificar se código de referral é único
        while db.query(User).filter(User.referral_code == referral_code).first():
            referral_code = generate_referral_code(user_data.email)
        
        # Buscar quem indicou (se fornecido código)
        referrer_id = None
        if user_data.referral_code:
            referrer = db.query(User).filter(
                User.referral_code == user_data.referral_code
            ).first()
            
            if referrer:
                referrer_id = referrer.id
                # Creditar bônus de referral (100k créditos)
                referrer.credits += settings.REFERRAL_BONUS_CREDITS
                logger.info(
                    f"Bônus de referral creditado: {settings.REFERRAL_BONUS_CREDITS} "
                    f"créditos para {referrer.email}"
                )
        
        # Criar novo usuário
        new_user = User(
            email=user_data.email,
            password_hash=password_hash,
            name=user_data.name,
            credits=settings.FREE_CREDITS_ON_SIGNUP,
            referral_code=referral_code,
            referred_by=referrer_id,
            is_active=True,
            is_verified=False,
            created_at=datetime.utcnow()
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"Novo usuário registrado: {new_user.email} (ID: {new_user.id})")
        
        return new_user
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Erro ao registrar usuário: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao registrar usuário"
        )


@router.post("/login", response_model=Token)
async def login(
    credentials: UserLogin,
    db: Session = Depends(get_db)
):
    """
    Login de usuário
    
    - Verifica email e senha
    - Gera access_token (30 min) e refresh_token (7 dias)
    - Atualiza last_login
    - Retorna tokens
    """
    try:
        # Buscar usuário por email
        user = db.query(User).filter(User.email == credentials.email).first()
        
        # Verificar se usuário existe e senha está correta
        if not user or not verify_password(credentials.password, user.password_hash):
            logger.warning(f"Tentativa de login falha: {credentials.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email ou senha incorretos"
            )
        
        # Verificar se usuário está ativo
        if not user.is_active:
            logger.warning(f"Tentativa de login de usuário inativo: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Conta inativa. Entre em contato com o suporte."
            )
        
        # Gerar tokens
        token_data = {
            "user_id": str(user.id),
            "email": user.email
        }
        
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)
        
        # Atualizar last_login
        user.last_login = datetime.utcnow()
        db.commit()
        
        logger.info(f"Login bem-sucedido: {user.email}")
        
        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro no login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno no login"
        )


@router.post("/refresh", response_model=Token)
async def refresh_token_endpoint(
    refresh_token: str,
    db: Session = Depends(get_db)
):
    """
    Renovar access token usando refresh token
    
    - Valida refresh_token
    - Gera novo access_token
    - Gera novo refresh_token (rotation para segurança)
    - Retorna novos tokens
    """
    try:
        # Verificar refresh token
        payload = verify_token(refresh_token, token_type="refresh")
        
        user_id = payload.get("user_id")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token inválido"
            )
        
        # Buscar usuário
        user = db.query(User).filter(User.id == user_id).first()
        
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuário não encontrado ou inativo"
            )
        
        # Gerar novos tokens (rotation)
        token_data = {
            "user_id": str(user.id),
            "email": user.email
        }
        
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data)
        
        logger.info(f"Tokens renovados para: {user.email}")
        
        return Token(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer"
        )
        
    except TokenError as e:
        logger.warning(f"Erro ao renovar token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido ou expirado"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro inesperado ao renovar token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro interno ao renovar token"
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """
    Retornar dados do usuário autenticado
    
    - Usa token JWT para identificar usuário
    - Retorna perfil completo
    """
    return current_user


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_active_user)
):
    """
    Logout (placeholder)
    
    - No futuro: adicionar token em blacklist no Redis
    - Por enquanto: apenas confirma logout
    """
    logger.info(f"Logout: {current_user.email}")
    
    return {
        "message": "Logout realizado com sucesso",
        "user_email": current_user.email
    }
