import hashlib
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models import TranslationCache, Translation
from app.database import redis_client
import json

# Configurar logging
logger = logging.getLogger(__name__)

class CacheService:
    """
    Sistema de cache inteligente para traduções
    
    Estratégia de cache em duas camadas:
    1. Redis (cache rápido, TTL 1 hora) - para sessão atual
    2. PostgreSQL (cache permanente) - para histórico
    
    Economia massiva: reutilizar traduções de trechos idênticos
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.redis_ttl = 3600  # 1 hora
    
    def generate_cache_key(
        self,
        text: str,
        source_lang: str,
        target_lang: str
    ) -> str:
        """
        Gerar chave única para o cache
        
        Args:
            text: Texto original
            source_lang: Idioma de origem
            target_lang: Idioma de destino
        
        Returns:
            Hash SHA256 do texto + idiomas
        
        Exemplo:
            key = generate_cache_key("Hello world", "en", "pt")
            # Returns: "a3f5b8c9..." (64 chars)
        """
        try:
            # Normalizar texto (lowercase, strip, remover espaços extras)
            normalized_text = ' '.join(text.strip().lower().split())
            
            # Criar string única: texto|source|target
            cache_string = f"{normalized_text}|{source_lang}|{target_lang}"
            
            # Gerar hash SHA256
            hash_obj = hashlib.sha256(cache_string.encode('utf-8'))
            return hash_obj.hexdigest()
            
        except Exception as e:
            logger.error(f"Erro ao gerar cache key: {str(e)}")
            raise
    
    def get_from_cache(
        self,
        text: str,
        source_lang: str,
        target_lang: str
    ) -> Optional[Dict[str, Any]]:
        """
        Buscar tradução no cache
        
        Fluxo:
        1. Gerar cache_key
        2. Buscar no Redis (rápido)
        3. Se não encontrar, buscar no PostgreSQL
        4. Se encontrar no PostgreSQL, salvar no Redis
        5. Incrementar hit_count
        6. Retornar tradução + metadata
        
        Args:
            text: Texto original
            source_lang: Idioma de origem
            target_lang: Idioma de destino
        
        Returns:
            Dict com:
            {
                "translated_text": str,
                "cache_id": UUID,
                "from_redis": bool,
                "hit_count": int
            }
            ou None se não encontrado
        """
        try:
            cache_key = self.generate_cache_key(text, source_lang, target_lang)
            
            # 1. Tentar Redis primeiro (rápido)
            redis_key = f"translation_cache:{cache_key}"
            cached_redis = None
            
            try:
                cached_redis = redis_client.get(redis_key)
            except Exception as redis_error:
                logger.warning(f"Redis indisponível: {str(redis_error)}. Continuando com PostgreSQL.")
            
            if cached_redis:
                try:
                    data = json.loads(cached_redis)
                    logger.debug(f"Cache hit no Redis: {redis_key}")
                    return {
                        "translated_text": data["translated_text"],
                        "cache_id": data["cache_id"],
                        "from_redis": True,
                        "hit_count": data.get("hit_count", 0)
                    }
                except json.JSONDecodeError as e:
                    logger.warning(f"Cache Redis corrompido: {str(e)}")
            
            # 2. Buscar no PostgreSQL
            cached_db = self.db.query(TranslationCache).filter(
                and_(
                    TranslationCache.text_hash == cache_key,
                    TranslationCache.source_language == source_lang,
                    TranslationCache.target_language == target_lang
                )
            ).first()
            
            if cached_db:
                # 3. Incrementar hit_count
                cached_db.hit_count += 1
                cached_db.last_used = datetime.utcnow()
                
                try:
                    self.db.commit()
                except Exception as db_error:
                    logger.error(f"Erro ao atualizar hit_count: {str(db_error)}")
                    self.db.rollback()
                
                # 4. Salvar no Redis para próximas buscas
                try:
                    redis_data = {
                        "translated_text": cached_db.translated_text,
                        "cache_id": str(cached_db.id),
                        "hit_count": cached_db.hit_count
                    }
                    redis_client.setex(
                        redis_key,
                        self.redis_ttl,
                        json.dumps(redis_data)
                    )
                except Exception as redis_error:
                    logger.warning(f"Erro ao salvar no Redis: {str(redis_error)}")
                
                logger.debug(f"Cache hit no PostgreSQL: {cache_key}, hits: {cached_db.hit_count}")
                return {
                    "translated_text": cached_db.translated_text,
                    "cache_id": cached_db.id,
                    "from_redis": False,
                    "hit_count": cached_db.hit_count
                }
            
            # Não encontrado
            logger.debug(f"Cache miss: {cache_key}")
            return None
            
        except Exception as e:
            logger.error(f"Erro ao buscar no cache: {str(e)}")
            return None
    
    def save_to_cache(
        self,
        original_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str
    ) -> TranslationCache:
        """
        Salvar tradução no cache
        
        Args:
            original_text: Texto original
            translated_text: Texto traduzido
            source_lang: Idioma de origem
            target_lang: Idioma de destino
        
        Returns:
            Objeto TranslationCache criado
        """
        try:
            text_hash = self.generate_cache_key(original_text, source_lang, target_lang)
            
            # Verificar se já existe (evitar duplicatas)
            existing = self.db.query(TranslationCache).filter(
                TranslationCache.text_hash == text_hash
            ).first()
            
            if existing:
                logger.debug(f"Cache já existe: {text_hash}")
                return existing
            
            # Criar novo cache entry
            cache_entry = TranslationCache(
                text_hash=text_hash,
                original_text=original_text,
                translated_text=translated_text,
                source_language=source_lang,
                target_language=target_lang,
                hit_count=0,
                created_at=datetime.utcnow(),
                last_used=datetime.utcnow()
            )
            
            self.db.add(cache_entry)
            self.db.commit()
            self.db.refresh(cache_entry)
            
            # Salvar no Redis também
            try:
                redis_key = f"translation_cache:{text_hash}"
                redis_data = {
                    "translated_text": translated_text,
                    "cache_id": str(cache_entry.id),
                    "hit_count": 0
                }
                redis_client.setex(redis_key, self.redis_ttl, json.dumps(redis_data))
            except Exception as redis_error:
                logger.warning(f"Erro ao salvar no Redis: {str(redis_error)}")
            
            logger.info(f"Cache salvo: {text_hash}, {len(original_text)} caracteres")
            return cache_entry
            
        except Exception as e:
            logger.error(f"Erro ao salvar no cache: {str(e)}")
            self.db.rollback()
            raise
    
    def batch_save_to_cache(
        self,
        translations: List[Dict[str, str]]
    ) -> List[TranslationCache]:
        """
        Salvar múltiplas traduções no cache em lote
        
        Args:
            translations: Lista de dicionários com:
                {
                    "original_text": str,
                    "translated_text": str,
                    "source_lang": str,
                    "target_lang": str
                }
        
        Returns:
            Lista de objetos TranslationCache criados
        """
        try:
            cache_entries = []
            
            for translation in translations:
                text_hash = self.generate_cache_key(
                    translation["original_text"],
                    translation["source_lang"],
                    translation["target_lang"]
                )
                
                # Verificar se já existe
                existing = self.db.query(TranslationCache).filter(
                    TranslationCache.text_hash == text_hash
                ).first()
                
                if existing:
                    cache_entries.append(existing)
                    continue
                
                # Criar novo cache entry
                cache_entry = TranslationCache(
                    text_hash=text_hash,
                    original_text=translation["original_text"],
                    translated_text=translation["translated_text"],
                    source_language=translation["source_lang"],
                    target_language=translation["target_lang"],
                    hit_count=0,
                    created_at=datetime.utcnow(),
                    last_used=datetime.utcnow()
                )
                
                cache_entries.append(cache_entry)
                self.db.add(cache_entry)
            
            self.db.commit()
            
            # Salvar no Redis também
            for cache_entry in cache_entries:
                try:
                    redis_key = f"translation_cache:{cache_entry.text_hash}"
                    redis_data = {
                        "translated_text": cache_entry.translated_text,
                        "cache_id": str(cache_entry.id),
                        "hit_count": 0
                    }
                    redis_client.setex(redis_key, self.redis_ttl, json.dumps(redis_data))
                except Exception as redis_error:
                    logger.warning(f"Erro ao salvar no Redis: {str(redis_error)}")
            
            logger.info(f"Batch cache salvo: {len(cache_entries)} entradas")
            return cache_entries
            
        except Exception as e:
            logger.error(f"Erro no batch save cache: {str(e)}")
            self.db.rollback()
            raise
    
    def get_cache_stats(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Estatísticas do cache
        
        Args:
            user_id: Se fornecido, stats específicas do usuário
        
        Returns:
            Dict com:
            {
                "total_entries": int,
                "total_hits": int,
                "top_translations": List[Dict],
                "cache_hit_rate": float (%)
            }
        """
        try:
            # Total de entradas no cache
            total_entries = self.db.query(func.count(TranslationCache.id)).scalar() or 0
            
            # Total de hits (reutilizações)
            total_hits = self.db.query(func.sum(TranslationCache.hit_count)).scalar() or 0
            
            # Top 10 traduções mais reutilizadas
            top_translations = self.db.query(
                TranslationCache.source_language,
                TranslationCache.target_language,
                TranslationCache.hit_count,
                TranslationCache.original_text
            ).order_by(
                TranslationCache.hit_count.desc()
            ).limit(10).all()
            
            # Cache hit rate geral
            cache_hit_rate = 0.0
            if total_entries > 0:
                cache_hit_rate = (total_hits / (total_entries + total_hits)) * 100
            
            # Se user_id fornecido, calcular hit rate do usuário
            user_cache_hit_rate = 0.0
            user_savings = {
                "credits_saved": 0,
                "money_saved_brl": 0.0,
                "percentage_saved": 0.0
            }
            
            if user_id:
                user_translations = self.db.query(Translation).filter(
                    Translation.user_id == user_id
                ).all()
                
                if user_translations:
                    total_chars = sum(t.actual_characters for t in user_translations)
                    cached_chars = sum(t.credits_saved or 0 for t in user_translations)
                    
                    if total_chars > 0:
                        user_cache_hit_rate = (cached_chars / total_chars) * 100
                    
                    user_savings = self.calculate_savings(total_chars, cached_chars)
            
            return {
                "total_entries": total_entries,
                "total_hits": total_hits,
                "top_translations": [
                    {
                        "languages": f"{t[0]} → {t[1]}",
                        "hits": t[2],
                        "preview": t[3][:50] + "..." if len(t[3]) > 50 else t[3]
                    }
                    for t in top_translations
                ],
                "cache_hit_rate": round(cache_hit_rate, 2),
                "user_cache_hit_rate": round(user_cache_hit_rate, 2),
                "user_savings": user_savings
            }
            
        except Exception as e:
            logger.error(f"Erro ao obter stats do cache: {str(e)}")
            return {
                "total_entries": 0,
                "total_hits": 0,
                "top_translations": [],
                "cache_hit_rate": 0.0,
                "user_cache_hit_rate": 0.0,
                "user_savings": {
                    "credits_saved": 0,
                    "money_saved_brl": 0.0,
                    "percentage_saved": 0.0
                }
            }
    
    def calculate_savings(
        self,
        total_characters: int,
        cached_characters: int
    ) -> Dict[str, Any]:
        """
        Calcular economia em créditos e R$
        
        Args:
            total_characters: Total de caracteres do texto
            cached_characters: Caracteres obtidos do cache
        
        Returns:
            Dict com economia em créditos e reais
        """
        try:
            # Custo DeepL: R$ 125 por 1 milhão de caracteres
            cost_per_char = 125.0 / 1_000_000
            
            credits_saved = cached_characters
            money_saved = cached_characters * cost_per_char
            percentage_saved = (cached_characters / total_characters * 100) if total_characters > 0 else 0
            
            return {
                "credits_saved": credits_saved,
                "money_saved_brl": round(money_saved, 2),
                "percentage_saved": round(percentage_saved, 2)
            }
            
        except Exception as e:
            logger.error(f"Erro ao calcular savings: {str(e)}")
            return {
                "credits_saved": 0,
                "money_saved_brl": 0.0,
                "percentage_saved": 0.0
            }
    
    def clear_old_cache(self, days_old: int = 90) -> int:
        """
        Limpar cache antigo não utilizado (manutenção)
        
        Args:
            days_old: Remover entradas não usadas há X dias
        
        Returns:
            Número de entradas removidas
        """
        try:
            from datetime import timedelta
            
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            old_entries = self.db.query(TranslationCache).filter(
                and_(
                    TranslationCache.last_used < cutoff_date,
                    TranslationCache.hit_count == 0  # Nunca reutilizado
                )
            ).all()
            
            count = len(old_entries)
            
            # Remover do Redis primeiro
            for entry in old_entries:
                try:
                    redis_key = f"translation_cache:{entry.text_hash}"
                    redis_client.delete(redis_key)
                except Exception as redis_error:
                    logger.warning(f"Erro ao deletar do Redis: {str(redis_error)}")
            
            # Remover do PostgreSQL
            for entry in old_entries:
                self.db.delete(entry)
            
            self.db.commit()
            
            logger.info(f"Cache antigo limpo: {count} entradas removidas")
            return count
            
        except Exception as e:
            logger.error(f"Erro ao limpar cache antigo: {str(e)}")
            self.db.rollback()
            return 0
    
    def get_cache_efficiency_report(self) -> Dict[str, Any]:
        """
        Relatório detalhado de eficiência do cache
        
        Returns:
            Dict com métricas detalhadas
        """
        try:
            # Estatísticas por idioma
            lang_stats = self.db.query(
                TranslationCache.source_language,
                TranslationCache.target_language,
                func.count(TranslationCache.id).label('entries'),
                func.sum(TranslationCache.hit_count).label('hits')
            ).group_by(
                TranslationCache.source_language,
                TranslationCache.target_language
            ).all()
            
            # Entradas mais recentes
            recent_entries = self.db.query(TranslationCache).order_by(
                TranslationCache.created_at.desc()
            ).limit(5).all()
            
            # Entradas mais utilizadas
            popular_entries = self.db.query(TranslationCache).order_by(
                TranslationCache.hit_count.desc()
            ).limit(5).all()
            
            return {
                "language_stats": [
                    {
                        "languages": f"{stat[0]} → {stat[1]}",
                        "entries": stat[2],
                        "hits": stat[3] or 0,
                        "efficiency": round((stat[3] or 0) / (stat[2] + (stat[3] or 0)) * 100, 2) if stat[2] > 0 else 0
                    }
                    for stat in lang_stats
                ],
                "recent_entries": [
                    {
                        "id": entry.id,
                        "languages": f"{entry.source_language} → {entry.target_language}",
                        "preview": entry.original_text[:100] + "..." if len(entry.original_text) > 100 else entry.original_text,
                        "created_at": entry.created_at,
                        "hits": entry.hit_count
                    }
                    for entry in recent_entries
                ],
                "popular_entries": [
                    {
                        "id": entry.id,
                        "languages": f"{entry.source_language} → {entry.target_language}",
                        "preview": entry.original_text[:100] + "..." if len(entry.original_text) > 100 else entry.original_text,
                        "hits": entry.hit_count,
                        "last_used": entry.last_used
                    }
                    for entry in popular_entries
                ]
            }
            
        except Exception as e:
            logger.error(f"Erro ao gerar relatório: {str(e)}")
            return {
                "language_stats": [],
                "recent_entries": [],
                "popular_entries": []
            }


# FUNÇÕES HELPER

def get_cache_service(db: Session) -> CacheService:
    """Factory function para criar CacheService"""
    return CacheService(db)

def batch_cache_lookup(
    texts: List[str],
    source_lang: str,
    target_lang: str,
    db: Session
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Busca em lote no cache - otimizada para múltiplos textos
    
    Args:
        texts: Lista de textos para buscar
        source_lang: Idioma de origem
        target_lang: Idioma de destino
        db: Sessão do banco
    
    Returns:
        Dict com cache_key -> resultado do cache (ou None se não encontrado)
    """
    cache_service = CacheService(db)
    results = {}
    
    for text in texts:
        cache_result = cache_service.get_from_cache(text, source_lang, target_lang)
        cache_key = cache_service.generate_cache_key(text, source_lang, target_lang)
        results[cache_key] = cache_result
    
    return results

def calculate_cache_savings_for_translation(
    translation_id: int,
    db: Session
) -> Dict[str, Any]:
    """
    Calcular economia específica para uma tradução
    
    Args:
        translation_id: ID da tradução
        db: Sessão do banco
    
    Returns:
        Dict com economia calculada
    """
    try:
        translation = db.query(Translation).filter(Translation.id == translation_id).first()
        if not translation:
            return {"error": "Tradução não encontrada"}
        
        cache_service = CacheService(db)
        return cache_service.calculate_savings(
            translation.actual_characters,
            translation.credits_saved or 0
        )
        
    except Exception as e:
        logger.error(f"Erro ao calcular savings da tradução: {str(e)}")
        return {
            "credits_saved": 0,
            "money_saved_brl": 0.0,
            "percentage_saved": 0.0
        }
