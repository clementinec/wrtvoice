"""
PDF Parser Module
Extracts essay text from PDF files for context initialization.
"""

import PyPDF2
import os
import re
import shutil
import subprocess
import tempfile


PDF_VIEWER_PATTERNS = [
    r"\d{1,2}/\d{1,2}/\d{4},?\s+\d{1,2}:\d{2}\s*(?:AM|PM)?\s*PDF\.js viewer\s*Page\s*\d+\s*of\s*\d+",
    r"PDF\.js viewer\s*Page\s*\d+\s*of\s*\d+",
    r"https?://\S+",
]

MIN_USEFUL_WORDS_WITH_VIEWER_CHROME = 200


class PDFParser:
    """Extracts text content from PDF files."""

    @staticmethod
    def extract_words_with_stats(pdf_path: str, max_words: int = 5000) -> dict:
        """
        Extract up to max_words from a PDF file and return truncation metadata.

        The parser tries multiple text paths because browser-viewer exports and
        scanned PDFs often expose only repeated viewer headers to PyPDF2.
        """
        try:
            text_candidates = []

            pypdf_text = PDFParser._extract_text_with_pypdf2(pdf_path)
            text_candidates.append(("pypdf2", pypdf_text))

            pdftotext_text = PDFParser._extract_text_with_pdftotext(pdf_path)
            if pdftotext_text:
                text_candidates.append(("pdftotext", pdftotext_text))

            method, cleaned_text, raw_text = PDFParser._best_text_candidate(text_candidates)
            boilerplate_detected = PDFParser._has_viewer_boilerplate(raw_text)
            ocr_attempted = False
            ocr_available = PDFParser._ocr_available()

            if PDFParser._needs_ocr(cleaned_text, raw_text):
                ocr_attempted = True
                ocr_text = PDFParser._extract_text_with_ocr(pdf_path) if ocr_available else ""
                cleaned_ocr_text = PDFParser._clean_extracted_text(ocr_text)
                if len(cleaned_ocr_text.split()) > len(cleaned_text.split()):
                    method = "ocr"
                    raw_text = ocr_text
                    cleaned_text = cleaned_ocr_text

            words = cleaned_text.split()
            extracted_words = words[:max_words]
            total_words = len(words)

            return {
                "text": " ".join(extracted_words),
                "words_extracted": len(extracted_words),
                "total_words": total_words,
                "word_limit": max_words,
                "truncated": total_words > max_words,
                "extraction_method": method,
                "boilerplate_detected": boilerplate_detected,
                "ocr_attempted": ocr_attempted,
                "ocr_available": ocr_available,
                "low_confidence_extraction": PDFParser._low_confidence(cleaned_text, raw_text)
            }

        except FileNotFoundError:
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        except Exception as e:
            raise Exception(f"Error reading PDF: {str(e)}")

    @staticmethod
    def _extract_text_with_pypdf2(pdf_path: str) -> str:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            return "\n".join((page.extract_text() or "") for page in pdf_reader.pages)

    @staticmethod
    def _extract_text_with_pdftotext(pdf_path: str) -> str:
        if not shutil.which("pdftotext"):
            return ""

        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False
        )
        return result.stdout if result.returncode == 0 else ""

    @staticmethod
    def _extract_text_with_ocr(pdf_path: str) -> str:
        try:
            import fitz
        except ImportError:
            return ""

        if not shutil.which("tesseract"):
            return ""

        ocr_pages = []
        document = fitz.open(pdf_path)

        for page in document:
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
                image_path = image_file.name
                image_file.write(pixmap.tobytes("png"))

            try:
                result = subprocess.run(
                    ["tesseract", image_path, "stdout", "--psm", "3"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False
                )
                if result.returncode == 0:
                    ocr_pages.append(result.stdout)
            finally:
                if os.path.exists(image_path):
                    os.remove(image_path)

        document.close()
        return "\n".join(ocr_pages)

    @staticmethod
    def _best_text_candidate(text_candidates: list) -> tuple:
        best_method = "pypdf2"
        best_raw_text = ""
        best_cleaned_text = ""
        best_word_count = -1

        for method, raw_text in text_candidates:
            cleaned_text = PDFParser._clean_extracted_text(raw_text)
            word_count = len(cleaned_text.split())
            if word_count > best_word_count:
                best_method = method
                best_raw_text = raw_text
                best_cleaned_text = cleaned_text
                best_word_count = word_count

        return best_method, best_cleaned_text, best_raw_text

    @staticmethod
    def _clean_extracted_text(text: str) -> str:
        cleaned = text or ""
        for pattern in PDF_VIEWER_PATTERNS:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    @staticmethod
    def _has_viewer_boilerplate(text: str) -> bool:
        lowered = (text or "").lower()
        return "pdf.js viewer" in lowered or "tfpdfviewer" in lowered

    @staticmethod
    def _needs_ocr(cleaned_text: str, raw_text: str) -> bool:
        cleaned_word_count = len(cleaned_text.split())
        return cleaned_word_count == 0 or (
            PDFParser._has_viewer_boilerplate(raw_text)
            and cleaned_word_count < MIN_USEFUL_WORDS_WITH_VIEWER_CHROME
        )

    @staticmethod
    def _low_confidence(cleaned_text: str, raw_text: str) -> bool:
        return PDFParser._needs_ocr(cleaned_text, raw_text)

    @staticmethod
    def _ocr_available() -> bool:
        if not shutil.which("tesseract"):
            return False
        try:
            import fitz
            return True
        except ImportError:
            return False

    @staticmethod
    def extract_first_n_words(pdf_path: str, n_words: int = 5000) -> str:
        """
        Extract the first N words from a PDF file.

        Kept for compatibility with older scripts.
        """
        try:
            return PDFParser.extract_words_with_stats(pdf_path, max_words=n_words)["text"]

        except FileNotFoundError:
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        except Exception as e:
            raise Exception(f"Error reading PDF: {str(e)}")

    @staticmethod
    def get_metadata(pdf_path: str) -> dict:
        """
        Extract metadata from PDF.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Dictionary containing PDF metadata
        """
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                metadata = pdf_reader.metadata

                return {
                    'title': metadata.get('/Title', 'Unknown') if metadata else 'Unknown',
                    'author': metadata.get('/Author', 'Unknown') if metadata else 'Unknown',
                    'pages': len(pdf_reader.pages)
                }
        except Exception as e:
            return {'error': str(e)}


if __name__ == "__main__":
    # Test the parser
    import sys

    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        parser = PDFParser()

        try:
            result = parser.extract_words_with_stats(pdf_path, 5000)
            print(
                f"Extracted {result['words_extracted']} of {result['total_words']} words "
                f"(limit: {result['word_limit']}, truncated: {result['truncated']}):\n"
            )
            print(result["text"])

            print("\n" + "="*50)
            metadata = parser.get_metadata(pdf_path)
            print(f"Metadata: {metadata}")

        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Usage: python pdf_parser.py <path_to_pdf>")
