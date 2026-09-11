import json
import re
import unicodedata
from pathlib import Path

import requests
import trafilatura

BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "sources" / "raw"
MANIFEST_PATH = BASE_DIR / "sources" / "paises.json"

RAW_DIR.mkdir(parents=True, exist_ok=True)


def _cargar_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _guardar_manifest(manifest: dict):
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def listar_paises() -> dict:
    return _cargar_manifest()


def cargar_fuente(codigo: str) -> str:
    manifest = _cargar_manifest()
    if codigo not in manifest:
        raise ValueError(f"País no reconocido: {codigo}")
    ruta = RAW_DIR / f"{codigo}.txt"
    if not ruta.exists():
        raise FileNotFoundError(f"Falta el texto de {codigo}")
    return ruta.read_text(encoding="utf-8")


def _slug(nombre: str) -> str:
    nfkd = unicodedata.normalize("NFKD", nombre)
    sin_tildes = "".join(c for c in nfkd if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")
    return slug or "pais"


def extraer_url(url: str, timeout: int = 20, verify_ssl: bool = True) -> str:
    respuesta = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}, verify=verify_ssl)
    respuesta.raise_for_status()
    texto = trafilatura.extract(respuesta.text)
    if not texto:
        raise RuntimeError(f"No se pudo extraer texto de {url}")
    return texto


def agregar_fuente_texto(nombre: str, texto: str) -> str:
    if not texto.strip():
        raise ValueError("El texto extraído está vacío.")

    codigo = _slug(nombre)
    manifest = _cargar_manifest()

    codigo_final = codigo
    contador = 2
    while codigo_final in manifest:
        codigo_final = f"{codigo}_{contador}"
        contador += 1

    (RAW_DIR / f"{codigo_final}.txt").write_text(texto, encoding="utf-8")
    manifest[codigo_final] = nombre
    _guardar_manifest(manifest)
    return codigo_final

def eliminar_fuente(codigo: str):
    manifest = _cargar_manifest()
    if codigo not in manifest:
        raise ValueError(f"País no reconocido: {codigo}")
    ruta = RAW_DIR / f"{codigo}.txt"
    if ruta.exists():
        ruta.unlink()
    del manifest[codigo]
    _guardar_manifest(manifest)