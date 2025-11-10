import logging
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any
import os

logger = logging.getLogger(__name__)


class EPUBParser:
    """Parser para arquivos EPUB"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.book = None
        self._load_epub()
    
    def _load_epub(self):
        """Carregar EPUB"""
        try:
            self.book = epub.read_epub(self.file_path)
            logger.info(f"EPUB carregado: {self.file_path}")
        except Exception as e:
            logger.error(f"Erro ao carregar EPUB: {str(e)}")
            raise ValueError(f"Erro ao carregar EPUB: {str(e)}")
    
    def _extract_text_from_html(self, html_content: str) -> str:
        """Extrair texto limpo de HTML"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remover tags de script e style
            for script in soup(["script", "style"]):
                script.decompose()
            
            text = soup.get_text()
            
            # Limpar espaços extras
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            return text
        except Exception as e:
            logger.error(f"Erro ao extrair texto de HTML: {str(e)}")
            return ""
    
    def extract_text(self, chapter_range: Optional[tuple] = None) -> str:
        """Extrair texto do EPUB"""
        try:
            texts = []
            items = list(self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
            
            if chapter_range:
                start, end = chapter_range
                items = items[start:end]
            
            for item in items:
                try:
                    html = item.get_content().decode('utf-8')
                    text = self._extract_text_from_html(html)
                    if text.strip():
                        texts.append(text)
                except:
                    continue
            
            full_text = "\n\n".join(texts)
            logger.debug(f"Extraídos {len(full_text)} caracteres de {len(texts)} capítulos")
            
            return full_text
            
        except Exception as e:
            logger.error(f"Erro ao extrair texto do EPUB: {str(e)}")
            raise ValueError(f"Erro ao extrair texto: {str(e)}")
    
    def extract_metadata(self) -> Dict[str, Any]:
        """Extrair metadados do EPUB"""
        try:
            title = self.book.get_metadata('DC', 'title')
            author = self.book.get_metadata('DC', 'creator')
            language = self.book.get_metadata('DC', 'language')
            
            return {
                "title": title[0][0] if title else "Sem título",
                "author": author[0][0] if author else "Desconhecido",
                "language": language[0][0] if language else "unknown",
                "chapters": self.get_total_chapters()
            }
        except Exception as e:
            logger.error(f"Erro ao extrair metadados: {str(e)}")
            return {
                "title": "Sem título",
                "author": "Desconhecido",
                "language": "unknown",
                "chapters": 0
            }
    
    def get_total_chapters(self) -> int:
        """Retornar total de capítulos"""
        return len(list(self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT)))
    
    def extract_chapter(self, chapter_num: int) -> str:
        """Extrair capítulo específico"""
        try:
            items = list(self.book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
            
            if chapter_num < 0 or chapter_num >= len(items):
                raise ValueError(f"Capítulo {chapter_num} não existe")
            
            item = items[chapter_num]
            html = item.get_content().decode('utf-8')
            return self._extract_text_from_html(html)
        except Exception as e:
            logger.error(f"Erro ao extrair capítulo {chapter_num}: {str(e)}")
            raise ValueError(f"Erro ao extrair capítulo: {str(e)}")
    
    def calculate_characters(self, chapter_range: Optional[tuple] = None) -> int:
        """Calcular total de caracteres"""
        text = self.extract_text(chapter_range)
        return len(text)


# Funções helper
def extract_text_from_epub(file_path: str) -> str:
    """Helper: extrair texto completo"""
    parser = EPUBParser(file_path)
    return parser.extract_text()


def extract_preview_from_epub(file_path: str, max_chapters: int = 3) -> str:
    """Helper: extrair preview de N capítulos"""
    parser = EPUBParser(file_path)
    return parser.extract_text((0, max_chapters))


def get_epub_info(file_path: str) -> Dict[str, Any]:
    """Helper: obter informações do EPUB"""
    try:
        parser = EPUBParser(file_path)
        metadata = parser.extract_metadata()
        total_chars = parser.calculate_characters()
        
        return {
            **metadata,
            "total_characters": total_chars,
            "estimated_pages": total_chars // 2500,
            "file_size_mb": round(os.path.getsize(file_path) / 1024 / 1024, 2)
        }
    except Exception as e:
        logger.error(f"Erro ao obter info do EPUB: {str(e)}")
        raise
