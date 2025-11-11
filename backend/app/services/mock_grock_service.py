# services/mock_grock_service.py
class MockGrockService:
    async def translate_text(self, text: str, target_lang: str) -> str:
        return f"[MOCK TRADUÇÃO] {text} - Traduzido para {target_lang}"
    
    async def translate_batch(self, texts: List[str], target_lang: str) -> List[str]:
        return [f"[MOCK TRADUÇÃO] {text}" for text in texts]

mock_grock_service = MockGrockService()
