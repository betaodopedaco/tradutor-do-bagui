import os
import groq
import logging
from typing import List
import asyncio

logger = logging.getLogger(__name__)

class GroqService:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("Groq API Key não configurada")
        self.client = groq.Groq(api_key=self.api_key)
    
    async def translate_text(self, text: str, target_lang: str = "português") -> str:
        """Traduz texto usando Groq AI mantendo estilo literário"""
        try:
            prompt = f"""
            TRADUZA este texto para {target_lang} mantendo:
            - O estilo literário original
            - O contexto emocional  
            - As nuances culturais
            - A fluência natural

            Texto para traduzir: "{text}"

            Retorne APENAS a tradução, sem explicações.
            """
            
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "Você é um tradutor literário especializado em preservar o estilo do autor."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                model="llama3-70b-8192",  # Modelo rápido e poderoso
                temperature=0.3,
                max_tokens=4000
            )
            
            translated_text = chat_completion.choices[0].message.content.strip()
            return translated_text
            
        except Exception as e:
            logger.error(f"Erro Groq translation: {e}")
            return f"[FALLBACK] {text}"
    
    async def translate_batch(self, texts: List[str], target_lang: str = "português") -> List[str]:
        """Traduz lote de textos mantendo consistência"""
        try:
            results = []
            for text in texts:
                translated = await self.translate_text(text, target_lang)
                results.append(translated)
                # Pequeno delay para evitar rate limiting
                await asyncio.sleep(0.2)
            return results
        except Exception as e:
            logger.error(f"Erro batch Groq: {e}")
            return [f"[FALLBACK] {text}" for text in texts]

# Instância global
groq_service = GroqService()
