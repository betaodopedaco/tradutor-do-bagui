import logging
from typing import Optional, Dict
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime
import json

from app.models import Translation, TranslationChunk, TranslationStatus, User
from app.services.cache_service import CacheService
from app.services.deepl_service import DeepLService
from app.services.text_splitter import TextSplitter
from app.database import redis_client

logger = logging.getLogger(__name__)


class TranslationService:
    """
    ORCHESTRATOR PRINCIPAL - Coordena todo o fluxo de tradução
    
    1. Validação de créditos
    2. Divisão em chunks
    3. Cache lookup
    4. Tradução (DeepL)
    5. Aplicação de glossário
    6. Salvamento de resultados
    7. Cálculo de economia
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.cache_service = CacheService(db)
        self.deepl_service = DeepLService()
    
    def process_translation(self, translation_id: UUID, text_content: str) -> Translation:
        """
        Processar tradução completa
        
        FLUXO COMPLETO:
        1. Buscar translation no banco
        2. Dividir texto em chunks
        3. Para cada chunk:
           a. Buscar no cache
           b. Se não encontrar: traduzir com DeepL
           c. Salvar no cache
           d. Criar TranslationChunk
           e. Atualizar progresso
        4. Calcular economia
        5. Debitar créditos do usuário
        6. Atualizar status para COMPLETED
        """
        # 1. Buscar translation
        translation = self.db.query(Translation).filter(
            Translation.id == translation_id
        ).first()
        
        if not translation:
            raise ValueError(f"Translation {translation_id} não encontrada")
        
        # Atualizar status
        translation.status = TranslationStatus.PROCESSING
        translation.started_at = datetime.utcnow()
        self.db.commit()
        
        try:
            # 2. Dividir em chunks
            text_splitter = TextSplitter(
                max_chunk_size=5000,
                glossary=translation.glossary
            )
            
            chunks = text_splitter.split_text(
                text_content,
                is_preview=translation.is_preview
            )
            
            total_chunks = len(chunks)
            logger.info(f"Texto dividido em {total_chunks} chunks")
            
            # Métricas
            total_translated_chars = 0
            cached_chars = 0
            
            # 3. Processar cada chunk
            for idx, chunk_data in enumerate(chunks):
                chunk_text = chunk_data["text"]
                chunk_order = chunk_data["order"]
                
                # a. Buscar no cache
                cached = self.cache_service.get_from_cache(
                    chunk_text,
                    translation.source_language,
                    translation.target_language
                )
                
                if cached:
                    # CACHE HIT! 🎉
                    translated_text = cached["translated_text"]
                    cache_id = cached["cache_id"]
                    from_cache = True
                    cached_chars += len(chunk_text)
                    
                    logger.info(f"Cache HIT: chunk {idx+1}/{total_chunks}")
                else:
                    # b. CACHE MISS - Traduzir com DeepL
                    translated_text = self.deepl_service.translate_text(
                        chunk_text,
                        translation.target_language,
                        translation.source_language,
                        translation.glossary
                    )
                    
                    # c. Salvar no cache
                    cache_entry = self.cache_service.save_to_cache(
                        chunk_text,
                        translated_text,
                        translation.source_language,
                        translation.target_language
                    )
                    
                    cache_id = cache_entry.id
                    from_cache = False
                    total_translated_chars += len(chunk_text)
                    
                    logger.info(f"Traduzido via DeepL: chunk {idx+1}/{total_chunks}")
                
                # d. Criar TranslationChunk
                translation_chunk = TranslationChunk(
                    translation_id=translation.id,
                    chunk_order=chunk_order,
                    original_text=chunk_text,
                    translated_text=translated_text,
                    cache_id=cache_id,
                    from_cache=from_cache,
                    character_count=len(chunk_text),
                    translated_at=datetime.utcnow()
                )
                
                self.db.add(translation_chunk)
                
                # e. Atualizar progresso
                progress = int((idx + 1) / total_chunks * 100)
                translation.progress = progress
                
                # Salvar progresso no Redis
                self._update_progress_redis(translation.id, progress, cached_chars)
                
                self.db.commit()
            
            # 4. Calcular economia
            credits_saved = cached_chars
            credits_used = total_translated_chars
            
            translation.credits_used = credits_used
            translation.credits_saved = credits_saved
            
            # 5. Debitar créditos (apenas o que realmente usou)
            if not translation.is_preview:
                user = translation.user
                user.credits -= credits_used
                
                logger.info(
                    f"Créditos debitados: {credits_used} "
                    f"(economizou {credits_saved} com cache)"
                )
            
            # 6. Atualizar status
            translation.status = TranslationStatus.COMPLETED
            translation.completed_at = datetime.utcnow()
            translation.progress = 100
            
            self.db.commit()
            self.db.refresh(translation)
            
            logger.info(
                f"Tradução completa: {translation.id} | "
                f"Total: {translation.total_characters} chars | "
                f"Usado: {credits_used} | "
                f"Economizado: {credits_saved} ({credits_saved/translation.total_characters*100:.1f}%)"
            )
            
            return translation
        
        except Exception as e:
            logger.error(f"Erro na tradução {translation_id}: {str(e)}")
            
            translation.status = TranslationStatus.FAILED
            translation.error_message = str(e)
            translation.completed_at = datetime.utcnow()
            
            self.db.commit()
            
            raise e
    
    def _update_progress_redis(self, translation_id: UUID, progress: int, cached_chars: int):
        """Atualizar progresso no Redis para UI em tempo real"""
        try:
            redis_key = f"translation_progress:{translation_id}"
            
            data = {
                "progress": progress,
                "cached_chars": cached_chars,
                "updated_at": datetime.utcnow().isoformat()
            }
            
            redis_client.setex(redis_key, 3600, json.dumps(data))
        except Exception as e:
            logger.warning(f"Erro ao atualizar progresso no Redis: {str(e)}")
    
    def get_translation_progress(self, translation_id: UUID) -> Dict:
        """Obter progresso da tradução (para polling do frontend)"""
        try:
            # Tentar Redis primeiro
            redis_key = f"translation_progress:{translation_id}"
            cached_progress = redis_client.get(redis_key)
            
            if cached_progress:
                data = json.loads(cached_progress)
                
                translation = self.db.query(Translation).filter(
                    Translation.id == translation_id
                ).first()
                
                return {
                    "translation_id": str(translation_id),
                    "status": translation.status.value if translation else "unknown",
                    "progress": data["progress"],
                    "cached_chars": data["cached_chars"],
                    "updated_at": data["updated_at"]
                }
        except Exception as e:
            logger.warning(f"Erro ao buscar progresso no Redis: {str(e)}")
        
        # Fallback: buscar do banco
        translation = self.db.query(Translation).filter(
            Translation.id == translation_id
        ).first()
        
        if not translation:
            raise ValueError(f"Translation {translation_id} não encontrada")
        
        return {
            "translation_id": str(translation_id),
            "status": translation.status.value,
            "progress": translation.progress,
            "cached_chars": translation.credits_saved,
            "characters_translated": translation.credits_used,
            "total_characters": translation.total_characters
        }


def get_translation_service(db: Session) -> TranslationService:
    """Factory function"""
    return TranslationService(db)
