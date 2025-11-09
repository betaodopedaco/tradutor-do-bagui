import logging
import deepl
from typing import Optional, Dict
import time
import re

from app.config import settings
from app.database import redis_client

logger = logging.getLogger(__name__)


class DeepLService:
    """Serviço de tradução usando DeepL API"""
    
    def __init__(self):
        self.translator = deepl.Translator(settings.DEEPL_API_KEY)
        self.max_chars_per_request = 500000
        self.max_requests_per_second = 5
        self.retry_attempts = 3
        self.backoff_multiplier = 2
    
    def _check_rate_limit(self) -> bool:
        """Rate limiting usando Redis"""
        try:
            rate_limit_key = "deepl:rate_limit"
            current_time = time.time()
            
            # Limpar requests antigos
            redis_client.zremrangebyscore(rate_limit_key, 0, current_time - 1)
            
            # Contar requests na janela atual
            current_count = redis_client.zcard(rate_limit_key)
            
            if current_count >= self.max_requests_per_second:
                time.sleep(0.2)
                return self._check_rate_limit()
            
            # Registrar novo request
            redis_client.zadd(rate_limit_key, {str(current_time): current_time})
            redis_client.expire(rate_limit_key, 2)
            
            return True
        except Exception as e:
            logger.warning(f"Erro no rate limiting (continuando): {str(e)}")
            return True
    
    def translate_text(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        glossary: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Traduzir texto usando DeepL API
        
        Args:
            text: Texto a ser traduzido
            target_lang: Idioma de destino (PT, EN, ES...)
            source_lang: Idioma de origem (None = auto-detect)
            glossary: Termos que não devem ser traduzidos
        
        Returns:
            Texto traduzido
        """
        if not text or not text.strip():
            return ""
        
        # Validar tamanho
        if len(text) > self.max_chars_per_request:
            raise ValueError(
                f"Texto muito grande ({len(text)} chars). "
                f"Máximo: {self.max_chars_per_request}"
            )
        
        # Aplicar glossário ANTES
        original_terms = {}
        if glossary:
            text, original_terms = self._protect_glossary_terms(text, glossary)
        
        # Retry com backoff
        for attempt in range(self.retry_attempts):
            try:
                # Rate limiting
                self._check_rate_limit()
                
                # Traduzir
                result = self.translator.translate_text(
                    text,
                    target_lang=target_lang.upper(),
                    source_lang=source_lang.upper() if source_lang else None
                )
                
                translated_text = result.text
                
                # Restaurar termos do glossário
                if original_terms:
                    translated_text = self._restore_glossary_terms(
                        translated_text,
                        original_terms
                    )
                
                logger.info(
                    f"Tradução OK: {len(text)} chars "
                    f"({source_lang or 'AUTO'} → {target_lang})"
                )
                
                return translated_text
            
            except deepl.DeepLException as e:
                logger.error(f"DeepL error (attempt {attempt + 1}/{self.retry_attempts}): {str(e)}")
                
                if attempt < self.retry_attempts - 1:
                    wait_time = self.backoff_multiplier ** attempt
                    logger.info(f"Aguardando {wait_time}s antes de retry...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Falha na tradução após {self.retry_attempts} tentativas: {str(e)}")
    
    def _protect_glossary_terms(self, text: str, glossary: Dict[str, str]) -> tuple:
        """Substituir termos do glossário por placeholders"""
        protected_text = text
        placeholders = {}
        
        sorted_terms = sorted(glossary.keys(), key=len, reverse=True)
        
        for idx, term in enumerate(sorted_terms):
            if term in protected_text:
                placeholder = f"GLOSSARY_TERM_{idx}"
                protected_text = protected_text.replace(term, placeholder)
                placeholders[placeholder] = glossary[term]
        
        return protected_text, placeholders
    
    def _restore_glossary_terms(self, text: str, placeholders: Dict[str, str]) -> str:
        """Restaurar termos originais"""
        restored_text = text
        
        for placeholder, original_term in placeholders.items():
            restored_text = restored_text.replace(placeholder, original_term)
        
        return restored_text
    
    def detect_language(self, text: str) -> str:
        """Detectar idioma do texto"""
        sample = text[:1000]
        
        try:
            result = self.translator.translate_text(sample, target_lang="EN")
            detected_lang = result.detected_source_lang
            logger.info(f"Idioma detectado: {detected_lang}")
            return detected_lang
        except Exception as e:
            logger.error(f"Erro ao detectar idioma: {str(e)}")
            return "EN"


def get_deepl_service() -> DeepLService:
    """Factory function"""
    return DeepLService()
