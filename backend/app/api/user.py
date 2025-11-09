from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Dict, Any
from datetime import datetime, timedelta

from app.database import get_db
from app.schemas.user import UserResponse, UserUpdate, CreditBalance
from app.schemas.payment import PurchaseHistory
from app.schemas.common import SuccessResponse
from app.models import User, Translation, CreditPurchase
from app.utils.dependencies import get_current_active_user
from app.config import settings

router = APIRouter(prefix="/user", tags=["User Profile"])


@router.get("/profile", response_model=UserResponse)
async def get_profile(current_user: User = Depends(get_current_active_user)):
    """
    Retornar perfil completo do usuário autenticado
    
    Returns:
        UserResponse: Dados do usuário incluindo ID, email, nome, créditos, status e timestamps
    """
    return current_user


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    updates: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Atualizar perfil do usuário (nome, email)
    
    Args:
        updates: Campos a serem atualizados (nome e/ou email)
        current_user: Usuário autenticado
        db: Sessão do banco de dados
        
    Returns:
        UserResponse: Usuário atualizado
        
    Raises:
        HTTPException: 400 se email já estiver em uso
    """
    try:
        update_data = updates.dict(exclude_unset=True)
        
        # Verificar se email foi fornecido e se é diferente do atual
        if 'email' in update_data and update_data['email'] != current_user.email:
            # Verificar se novo email já está em uso por outro usuário
            existing_user = db.query(User).filter(
                User.email == update_data['email'],
                User.id != current_user.id
            ).first()
            
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email já está em uso por outro usuário"
                )
            
            current_user.email = update_data['email']
        
        # Atualizar nome se fornecido
        if 'name' in update_data:
            current_user.name = update_data['name']
        
        # Atualizar timestamps
        current_user.updated_at = datetime.utcnow()
        
        db.commit()
        db.refresh(current_user)
        
        return current_user
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar perfil: {str(e)}"
        )


@router.get("/credits", response_model=CreditBalance)
async def get_credits(current_user: User = Depends(get_current_active_user)):
    """
    Retornar saldo de créditos do usuário e estimativa de uso
    
    Returns:
        CreditBalance: Saldo atual de créditos e estimativas de tradução
    """
    # Calcular quantos livros pode traduzir (estimativa: 1 livro = 50.000 caracteres)
    books_can_translate = current_user.credits // 50000
    
    return CreditBalance(
        credits=current_user.credits,
        books_can_translate=books_can_translate,
        estimated_pages=books_can_translate * 250,  # 250 páginas por livro
        last_updated=datetime.utcnow()
    )


@router.get("/usage-stats")
async def get_usage_stats(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    period: str = Query("all", description="Período: last_week, last_month, last_year, all")
):
    """
    Estatísticas detalhadas de uso do usuário
    
    Args:
        period: Filtro por período temporal
        current_user: Usuário autenticado
        db: Sessão do banco de dados
        
    Returns:
        Dict: Estatísticas completas de uso
    """
    try:
        # Definir filtro de data baseado no período
        date_filter = None
        if period == "last_week":
            date_filter = datetime.utcnow() - timedelta(days=7)
        elif period == "last_month":
            date_filter = datetime.utcnow() - timedelta(days=30)
        elif period == "last_year":
            date_filter = datetime.utcnow() - timedelta(days=365)
        
        # Query base com filtro de usuário
        base_query = db.query(Translation).filter(Translation.user_id == current_user.id)
        
        if date_filter:
            base_query = base_query.filter(Translation.created_at >= date_filter)
        
        # Estatísticas básicas
        total_translations = base_query.count()
        
        total_characters = db.query(func.coalesce(func.sum(Translation.total_characters), 0)).filter(
            Translation.user_id == current_user.id
        ).scalar()
        
        total_saved_with_cache = db.query(func.coalesce(func.sum(Translation.credits_saved), 0)).filter(
            Translation.user_id == current_user.id
        ).scalar()
        
        total_credits_spent = db.query(func.coalesce(func.sum(Translation.credits_used), 0)).filter(
            Translation.user_id == current_user.id
        ).scalar()
        
        # Estatísticas por idioma
        translations_by_language = db.query(
            Translation.target_language,
            func.count(Translation.id).label('count'),
            func.sum(Translation.total_characters).label('total_chars')
        ).filter(Translation.user_id == current_user.id).group_by(Translation.target_language).all()
        
        # Últimas traduções
        recent_translations = db.query(Translation).filter(
            Translation.user_id == current_user.id
        ).order_by(desc(Translation.created_at)).limit(5).all()
        
        # Estatísticas de eficiência
        cache_efficiency = 0
        if total_credits_spent > 0:
            cache_efficiency = round((total_saved_with_cache / total_credits_spent) * 100, 2)
        
        # Média de caracteres por tradução
        avg_chars_per_translation = 0
        if total_translations > 0:
            avg_chars_per_translation = round(total_characters / total_translations)
        
        return {
            "period": period,
            "summary": {
                "total_translations": total_translations,
                "total_characters": total_characters,
                "total_saved_with_cache": total_saved_with_cache,
                "total_credits_spent": total_credits_spent,
                "cache_efficiency_percentage": cache_efficiency,
                "avg_chars_per_translation": avg_chars_per_translation
            },
            "by_language": [
                {
                    "language": lang,
                    "translation_count": count,
                    "total_characters": total_chars or 0
                }
                for lang, count, total_chars in translations_by_language
            ],
            "recent_translations": [
                {
                    "id": trans.id,
                    "filename": trans.filename,
                    "source_language": trans.source_language,
                    "target_language": trans.target_language,
                    "total_characters": trans.total_characters,
                    "status": trans.status,
                    "created_at": trans.created_at
                }
                for trans in recent_translations
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter estatísticas: {str(e)}"
        )


@router.get("/referrals")
async def get_referrals(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Sistema de referral - informações sobre indicações
    
    Returns:
        Dict: Dados de referral incluindo código, indicações e créditos ganhos
    """
    try:
        # Buscar usuários indicados
        referred_users = db.query(User).filter(
            User.referred_by == current_user.id
        ).all()
        
        # Calcular créditos ganhos (100.000 por indicação)
        credits_per_referral = 100000
        total_credits_earned = len(referred_users) * credits_per_referral
        
        # Mascarar emails dos indicados
        masked_referrals = []
        for user in referred_users:
            email_parts = user.email.split('@')
            if len(email_parts) == 2:
                masked_email = email_parts[0][:3] + "***@" + email_parts[1]
            else:
                masked_email = "***@unknown.com"
            
            masked_referrals.append({
                "email": masked_email,
                "joined_at": user.created_at,
                "is_active": user.is_active
            })
        
        return {
            "referral_code": current_user.referral_code,
            "referral_link": f"{settings.FRONTEND_URL}/register?ref={current_user.referral_code}",
            "total_referrals": len(referred_users),
            "credits_earned": total_credits_earned,
            "credits_per_referral": credits_per_referral,
            "referred_users": masked_referrals,
            "instructions": f"Compartilhe seu link e ganhe {credits_per_referral:,} créditos por cada amigo que se cadastrar.".replace(',', '.')
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter dados de referral: {str(e)}"
        )


@router.get("/purchase-history", response_model=SuccessResponse[List[PurchaseHistory]])
async def get_purchase_history(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=100, description="Número de itens por página"),
    offset: int = Query(0, ge=0, description="Offset para paginação"),
    status_filter: str = Query(None, description="Filtrar por status: completed, pending, failed")
):
    """
    Histórico de compras de créditos do usuário
    
    Args:
        limit: Limite de itens por página (1-100)
        offset: Offset para paginação
        status_filter: Filtrar por status de pagamento
        current_user: Usuário autenticado
        db: Sessão do banco de dados
        
    Returns:
        List[PurchaseHistory]: Lista paginada de compras
    """
    try:
        # Query base
        query = db.query(CreditPurchase).filter(
            CreditPurchase.user_id == current_user.id
        )
        
        # Aplicar filtro de status se fornecido
        if status_filter:
            query = query.filter(CreditPurchase.payment_status == status_filter)
        
        # Obter total para paginação
        total = query.count()
        
        # Obter compras com ordenação e paginação
        purchases = query.order_by(desc(CreditPurchase.created_at)).offset(offset).limit(limit).all()
        
        # Converter para schema de resposta
        purchase_history = [
            PurchaseHistory(
                id=purchase.id,
                package_name=purchase.package_name,
                credits=purchase.credits,
                price_paid=purchase.price_paid,
                payment_status=purchase.payment_status,
                payment_method=purchase.payment_method,
                created_at=purchase.created_at,
                completed_at=purchase.completed_at
            )
            for purchase in purchases
        ]
        
        return SuccessResponse.create(
            message="Histórico de compras obtido com sucesso",
            data={
                "purchases": purchase_history,
                "pagination": {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "has_more": (offset + limit) < total
                }
            }
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao obter histórico de compras: {str(e)}"
        )


@router.get("/dashboard")
async def get_user_dashboard(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Dashboard completo do usuário - resumo de todas as informações
    
    Returns:
        Dict: Dados consolidados para o dashboard
    """
    try:
        # Obter estatísticas básicas
        total_translations = db.query(func.count(Translation.id)).filter(
            Translation.user_id == current_user.id
        ).scalar()
        
        total_characters = db.query(func.coalesce(func.sum(Translation.total_characters), 0)).filter(
            Translation.user_id == current_user.id
        ).scalar()
        
        # Obter traduções recentes
        recent_translations = db.query(Translation).filter(
            Translation.user_id == current_user.id
        ).order_by(desc(Translation.created_at)).limit(3).all()
        
        # Obter compras recentes
        recent_purchases = db.query(CreditPurchase).filter(
            CreditPurchase.user_id == current_user.id
        ).order_by(desc(CreditPurchase.created_at)).limit(3).all()
        
        # Estatísticas de referral
        referral_count = db.query(func.count(User.id)).filter(
            User.referred_by == current_user.id
        ).scalar()
        
        return {
            "user": {
                "name": current_user.name,
                "email": current_user.email,
                "credits": current_user.credits,
                "joined_at": current_user.created_at
            },
            "quick_stats": {
                "total_translations": total_translations,
                "total_characters": total_characters,
                "referral_count": referral_count,
                "credits_from_referrals": referral_count * 100000
            },
            "recent_activity": {
                "translations": [
                    {
                        "id": trans.id,
                        "filename": trans.filename,
                        "languages": f"{trans.source_language} → {trans.target_language}",
                        "characters": trans.total_characters,
                        "status": trans.status,
                        "created_at": trans.created_at
                    }
                    for trans in recent_translations
                ],
                "purchases": [
                    {
                        "id": purchase.id,
                        "credits": purchase.credits,
                        "price": purchase.price_paid,
                        "status": purchase.payment_status,
                        "created_at": purchase.created_at
                    }
                    for purchase in recent_purchases
                ]
            },
            "actions": [
                {
                    "title": "Traduzir Livro",
                    "description": "Iniciar nova tradução",
                    "action": "translate",
                    "icon": "book"
                },
                {
                    "title": "Comprar Créditos", 
                    "description": "Adicionar mais créditos à conta",
                    "action": "buy_credits",
                    "icon": "credit_card"
                },
                {
                    "title": "Convidar Amigos",
                    "description": "Ganhe créditos indicando amigos",
                    "action": "refer_friends", 
                    "icon": "group"
                }
            ]
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao carregar dashboard: {str(e)}"
        )
