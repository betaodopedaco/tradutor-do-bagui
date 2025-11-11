import asyncio
from typing import List, Dict, Any
from .groq_service import groq_service
import logging

logger = logging.getLogger(__name__)

class TranslationService:
    def __init__(self):
        self.translator = groq_service

    async def process_translation(self, text: str, target_language: str = "pt") -> Dict[str, Any]:
        """Processa tradução de texto usando Groq AI"""
        try:
            print(f"📤 Traduzindo: '{text}' para {target_language}")
            
            translated_text = await self.translator.translate_text(text, target_language)
            
            print(f"✅ Traduzido: '{translated_text}'")
            
            return {
                "status": "success",
                "original_text": text,
                "translated_text": translated_text,
                "target_language": target_language,
                "model": "Groq Llama3"
            }
        except Exception as e:
            logger.error(f"Erro na tradução: {e}")
            return {
                "status": "error", 
                "error": str(e),
                "original_text": text,
                "target_language": target_language
            }

# Instância global
translation_service = TranslationService()
