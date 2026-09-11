import pdfplumber
from docx import Document


def extraer_texto(ruta_archivo: str) -> str:
    if ruta_archivo.endswith(".pdf"):
        return extraer_pdf(ruta_archivo)
    elif ruta_archivo.endswith(".docx"):
        return extraer_docx(ruta_archivo)
    else:
        raise ValueError("Formato no soportado, solo PDF o DOCX")


def extraer_pdf(ruta_archivo: str) -> str:
    texto = ""
    with pdfplumber.open(ruta_archivo) as pdf:
        for pagina in pdf.pages:
            texto += pagina.extract_text() or ""
            texto += "\n"
    return texto


def extraer_docx(ruta_archivo: str) -> str:
    doc = Document(ruta_archivo)
    return "\n".join(p.text for p in doc.paragraphs)