"""
PDF Parser Module
Extracts the first 500 words from a PDF file for context initialization.
"""

import PyPDF2
from typing import Optional


class PDFParser:
    """Extracts text content from PDF files."""

    @staticmethod
    def extract_first_n_words(pdf_path: str, n_words: int = 500) -> str:
        """
        Extract the first N words from a PDF file.

        Args:
            pdf_path: Path to the PDF file
            n_words: Number of words to extract (default: 500)

        Returns:
            String containing the first N words

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            Exception: If PDF cannot be read
        """
        try:
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)

                # Extract text from all pages until we have enough words
                all_text = []
                word_count = 0

                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text = page.extract_text()

                    # Split into words and accumulate
                    words = text.split()
                    for word in words:
                        if word_count >= n_words:
                            break
                        all_text.append(word)
                        word_count += 1

                    if word_count >= n_words:
                        break

                return ' '.join(all_text)

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
            text = parser.extract_first_n_words(pdf_path, 500)
            print(f"Extracted {len(text.split())} words:\n")
            print(text)

            print("\n" + "="*50)
            metadata = parser.get_metadata(pdf_path)
            print(f"Metadata: {metadata}")

        except Exception as e:
            print(f"Error: {e}")
    else:
        print("Usage: python pdf_parser.py <path_to_pdf>")
