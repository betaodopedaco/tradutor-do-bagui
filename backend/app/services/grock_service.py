import os
import httpx
import logging
from typing import List
import asyncio

logger = logging.getLogger(__name__)

class GrockService:
    def __init__(self):
        self.api_key = os.getenv("GROCK_API_KEY", "sua-chave-grock-aqui")
        self.base_url = "https://api.x.ai/v1/chat/completions"  # URL exemplo - ajuste se necessário
    
    async def translate_text(self, text: str, target_lang: str = "português brasileiro") -> str:
        """Traduz texto usando Grock AI mantendo estilo literário"""
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
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": "grock",  # ou o modelo específico do Grock
                "messages": [
                    {"role": "system", "content": "Você é um tradutor literário especializado."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,  # Mais consistente para tradução
                "max_tokens": 4000
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.base_url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                
                translated_text = result["choices"][0]["message"]["content"].strip()
                return translated_text
                
        except Exception as e:
            logger.error(f"Erro Grock translation: {e}")
            # Fallback: retorna texto mock para testes
            return f"[TRADUÇÃO GROCK] {text}"
    
    async def translate_batch(self, texts: List[str], target_lang: str = "português brasileiro") -> List[str]:
        """Traduz lote de textos mantendo consistência"""
        try:
            results = []
            for text in texts:
                translated = await self.translate_text(text, target_lang)
                results.append(translated)
                # Delay para evitar rate limiting
                await asyncio.sleep(0.5)
            return results
        except Exception as e:
            logger.error(f"Erro batch Grock: {e}")
            return [f"[TRADUÇÃO GROCK] {text}" for text in texts]

# Instância global
grock_service = GrockService()
