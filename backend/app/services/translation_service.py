# No translation_service.py, substitua:
# from services.deepl_service import deepl_service
from services.grock_service import grock_service

class TranslationService:
    def __init__(self):
        # self.deepl_service = deepl_service  # Comentar
        self.grock_service = grock_service    # Adicionar
        # ... resto do código igual
    
    async def _translate_chunks(self, chunks: List[str], target_language: str) -> List[str]:
        """Traduz chunks usando Grock AI"""
        return await self.grock_service.translate_batch(chunks, target_language)
