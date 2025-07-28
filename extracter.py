import bs4

from pdfminer.high_level import extract_text
def extract (path):
    return extract_text(path)

from google.cloud import vision
def ocr_pdf(file_path_or_gcs_uri):
    client = vision.ImageAnnotatorClient();
    resp = client.document_text_detection({"source": {"gcs_image_uri": file_path_or_gcs_uri }})
    return resp.full_text_annotation

from pdfminer.high_level import extract_text
def extract_pdf_text(path):
    return extract_text(path)

from ebooklib import epub
from bs4 import BeautifulSoup
def extract_epub_text(path):
    book = epub.read_epub(path)
    text = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text.append(soup.get_text(seperator  = " "))
    return "\n\n".join(text)