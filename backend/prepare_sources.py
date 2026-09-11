import os
import tempfile
from pathlib import Path

import pdfplumber
import requests
import trafilatura

from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "sources" / "raw"
PDF_DIR = BASE_DIR / "sources" / "pdfs"

RAW_DIR.mkdir(parents=True, exist_ok=True)

FUENTES = {
    "chile": {"type": "pdf", "file": "Legilación de Chile.pdf"},
    "uk": {"type": "pdf", "file": "Legilación de UK.pdf"},
    "canada": {"type": "pdf", "file": "Legilación de canada.pdf"},
    "finlandia": {"type": "pdf", "file": "Legilación de finlandia.pdf"},
    "francia": {"type": "pdf", "file": "Legilación de francia.pdf"},
    "italia": {
        "type": "pdf",
        "file": "codigo civil italiano.pdf",
        "section_start": "SOCIETA' COOPERATIVE E DELLE MUTUE ASSICURATRICI",
        "section_end": "TITOLO VII",
    },
    "espana": {"type": "url", "url": "https://www.boe.es/buscar/act.php?id=BOE-A-1999-15681"},
    "nueva_zelanda": {"type": "pdf_url", "url": "https://faolex.fao.org/docs/pdf/nze178771.pdf"},
    "argentina": {"type": "url", "url": "https://servicios.infoleg.gob.ar/infolegInternet/anexos/15000-19999/18462/texact.htm"},
    "uruguay": {"type": "url", "url": "https://www.impo.com.uy/bases/leyes/18407-2008"},
    "brasil": {"type": "url", "url": "https://www.planalto.gov.br/ccivil_03/leis/l5764.htm"},
    "alemania": {"type": "url", "url": "https://www.gesetze-im-internet.de/geng/"},
    "suecia": {"type": "url", "url": "https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/lag-2018672-om-ekonomiska-foreningar_sfs-2018-672/"},
    "portugal": {"type": "url", "url": "https://diariodarepublica.pt/dr/detalhe/lei/119-2015-70139955"},
    "colombia": {"type": "url", "url": "https://www.funcionpublica.gov.co/eva/gestornormativo/norma.php?i=9211", "verify_ssl": False},
}


def extraer_pdf(path, section_start=None, section_end=None):
    texto = ""
    with pdfplumber.open(path) as pdf:
        for pagina in pdf.pages:
            texto += (pagina.extract_text() or "") + "\n"
    if section_start:
        inicio = texto.find(section_start)
        if inicio != -1:
            fin = texto.find(section_end, inicio) if section_end else len(texto)
            texto = texto[inicio:fin if fin != -1 else len(texto)]
    return texto


def extraer_pdf_url(url, timeout=30, verify_ssl=True):
    respuesta = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}, verify=verify_ssl)
    respuesta.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(respuesta.content)
        ruta_temporal = tmp.name
    try:
        return extraer_pdf(ruta_temporal)
    finally:
        os.remove(ruta_temporal)


def extraer_url(url, timeout=20, verify_ssl=True):
    respuesta = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}, verify=verify_ssl)
    respuesta.raise_for_status()
    texto = trafilatura.extract(respuesta.text, favor_recall=True)
    if not texto:
        sopa = BeautifulSoup(respuesta.text, "html.parser")
        texto = sopa.get_text(separator="\n", strip=True)
    if not texto:
        raise RuntimeError(f"No se pudo extraer texto de {url}")
    return texto


NOMBRES = {
    "chile": "Chile", "uk": "Reino Unido", "canada": "Canadá", "finlandia": "Finlandia",
    "francia": "Francia", "italia": "Italia", "espana": "España", "nueva_zelanda": "Nueva Zelanda",
    "argentina": "Argentina", "uruguay": "Uruguay", "brasil": "Brasil", "alemania": "Alemania",
    "suecia": "Suecia", "portugal": "Portugal", "colombia": "Colombia",
}


def main():
    from search import _cargar_manifest, _guardar_manifest
    manifest = _cargar_manifest()
    pendientes = []

    for pais, cfg in FUENTES.items():
        raw_path = RAW_DIR / f"{pais}.txt"
        if raw_path.exists():
            print(f"{pais}: ya extraído, saltando")
            manifest[pais] = NOMBRES[pais]
            continue

        print(f"Extrayendo {pais}...")
        try:
            if cfg["type"] == "pdf":
                texto = extraer_pdf(PDF_DIR / cfg["file"], cfg.get("section_start"), cfg.get("section_end"))
            elif cfg["type"] == "pdf_url":
                texto = extraer_pdf_url(cfg["url"], verify_ssl=cfg.get("verify_ssl", True))
            else:
                texto = extraer_url(cfg["url"], verify_ssl=cfg.get("verify_ssl", True))
            raw_path.write_text(texto, encoding="utf-8")
            manifest[pais] = NOMBRES[pais]
            print(f"  {pais}: OK ({len(texto)} caracteres)")
        except Exception as e:
            print(f"  {pais}: FALLÓ ({e})")
            pendientes.append(pais)

    _guardar_manifest(manifest)
    print("\nListo. Revisa backend/sources/raw/ y backend/sources/paises.json")
    if pendientes:
        print(f"Quedaron pendientes: {', '.join(pendientes)}")


if __name__ == "__main__":
    main()