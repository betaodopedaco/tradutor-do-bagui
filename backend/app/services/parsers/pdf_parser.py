import logging
from PyPDF2 import PdfReader
from typing import Optional, Dict, Any
import os

logger = logging.getLogger(__name__)


class PDFParser:
    """Parser para arquivos PDF"""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.reader = None
        self._load_pdf()
    
    def _load_pdf(self):
        """Carregar PDF"""
        try:
            self.reader = PdfReader(self.file_path)
            logger.info(f"PDF carregado: {self.file_path} ({len(self.reader.pages)} páginas)")
        except Exception as e:
            logger.error(f"Erro ao carregar PDF: {str(e)}")
            raise ValueError(f"Erro ao carregar PDF: {str(e)}")
    
    def extract_text(self, start_page: Optional[int] = None, end_page: Optional[int] = None) -> str:
        """Extrair texto do PDF"""
        try:
            start = start_page or 0
            end = end_page or len(self.reader.pages)
            
            text_parts = []
            for page_num in range(start, end):
                if page_num >= len(self.reader.pages):
                    break
                    
                page = self.reader.pages[page_num]
                text = page.extract_text()
                if text.strip():
                    text_parts.append(text)
            
            full_text = "\n\n".join(text_parts)
            logger.debug(f"Extraídos {len(full_text)} caracteres de {len(text_parts)} páginas")
            
            return full_text.strip()
            
        except Exception as e:
            logger.error(f"Erro ao extrair texto do PDF: {str(e)}")
            raise ValueError(f"Erro ao extrair texto: {str(e)}")
    
    def extract_metadata(self) -> Dict[str, Any]:
        """Extrair metadados do PDF"""
        try:
            metadata = self.reader.metadata or {}
            
            return {
                "title": metadata.get("/Title", "Sem título") if metadata.get("/Title") else "Sem título",
                "author": metadata.get("/Author", "Desconhecido") if metadata.get("/Author") else "Desconhecido",
                "pages": len(self.reader.pages),
                "creator": metadata.get("/Creator", ""),
                "producer": metadata.get("/Producer", "")
            }
        except Exception as e:
            logger.error(f"Erro ao extrair metadados: {str(e)}")
            return {
                "title": "Sem título",
                "author": "Desconhecido",
                "pages": len(self.reader.pages) if self.reader else 0,
                "creator": "",
                "producer": ""
            }
    
    def get_total_pages(self) -> int:
        """Retornar total de páginas"""
        return len(self.reader.pages)
    
    def extract_page(self, page_num: int) -> str:
        """Extrair texto de uma página específica"""
        try:
            if page_num < 0 or page_num >= len(self.reader.pages):
                raise ValueError(f"Página {page_num} não existe")
            
            page = self.reader.pages[page_num]
            return page.extract_text()
        except Exception as e:
            logger.error(f"Erro ao extrair página {page_num}: {str(e)}")
            raise ValueError(f"Erro ao extrair página: {str(e)}")
    
    def extract_pages_range(self, start: int, end: int) -> str:
        """Extrair intervalo de páginas"""
        return self.extract_text(start, end)
    
    def calculate_characters(self, start_page: Optional[int] = None, end_page: Optional[int] = None) -> int:
        """Calcular total de caracteres"""
        text = self.extract_text(start_page, end_page)
        return len(text)


# Funções helper
def extract_text_from_pdf(file_path: str) -> str:
    """Helper: extrair texto completo"""
    parser = PDFParser(file_path)
    return parser.extract_text()


def extract_preview_from_pdf(file_path: str, max_pages: int = 3) -> str:
    """Helper: extrair preview de N páginas"""
    parser = PDFParser(file_path)
    return parser.extract_text(0, max_pages)


def get_pdf_info(file_path: str) -> Dict[str, Any]:
    """Helper: obter informações do PDF"""
    try:
        parser = PDFParser(file_path)
        metadata = parser.extract_metadata()
        total_chars = parser.calculate_characters()
        
        return {
            **metadata,
            "total_characters": total_chars,
            "estimated_pages": metadata["pages"],
            "file_size_mb": round(os.path.getsize(file_path) / 1024 / 1024, 2)
        }
    except Exception as e:
        logger.error(f"Erro ao obter info do PDF: {str(e)}")
        raise
