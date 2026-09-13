import json
import logging
import os
import re
import unicodedata
from pathlib import Path

import requests
import trafilatura
from google.cloud import storage

logger = logging.getLogger("leyai")

BASE_DIR = Path(__file__).parent
RAW_DIR = BASE_DIR / "sources" / "raw"
LOCAL_MANIFEST_PATH = BASE_DIR / "sources" / "paises.json"

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

_storage_client = None


def _cliente_storage():
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client


def _bucket():
    if not BUCKET_NAME:
        raise RuntimeError("Falta la variable de entorno GCS_BUCKET_NAME")
    return _cliente_storage().bucket(BUCKET_NAME)


# ---------------------------------------------------------------------------
# Manifiesto
# ---------------------------------------------------------------------------

def _cargar_manifest_nube() -> dict:
    blob = _bucket().blob("paises.json")
    if not blob.exists():
        return {}
    return json.loads(blob.download_as_text())


def _guardar_manifest_nube(manifest: dict):
    blob = _bucket().blob("paises.json")
    blob.upload_from_string(
        json.dumps(manifest, ensure_ascii=False, indent=2), content_type="application/json"
    )


def _cargar_manifest_local() -> dict:
    if not LOCAL_MANIFEST_PATH.exists():
        return {}
    return json.loads(LOCAL_MANIFEST_PATH.read_text(encoding="utf-8"))


def _guardar_manifest_local(manifest: dict):
    LOCAL_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# Nombres que usa prepare_sources.py, que trabaja solo con el manifiesto local.
_cargar_manifest = _cargar_manifest_local
_guardar_manifest = _guardar_manifest_local


def listar_paises() -> dict:
    """Los 15 base que viajan en la imagen, más los agregados desde la app."""
    manifest = dict(_cargar_manifest_local())
    try:
        manifest.update(_cargar_manifest_nube())
    except Exception as e:
        # Permite trabajar en local sin credenciales de Google Cloud.
        logger.warning("No se pudo leer el manifiesto del bucket, %s", e)
    return manifest


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------

def cargar_fuente(codigo: str) -> str:
    ruta_local = RAW_DIR / f"{codigo}.txt"
    if ruta_local.exists():
        return ruta_local.read_text(encoding="utf-8")

    blob = _bucket().blob(f"raw/{codigo}.txt")
    if not blob.exists():
        raise FileNotFoundError(f"Falta el texto de {codigo}")
    return blob.download_as_text()


def _slug(nombre: str) -> str:
    nfkd = unicodedata.normalize("NFKD", nombre)
    sin_tildes = "".join(c for c in nfkd if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")
    return slug or "pais"


def extraer_url(url: str, timeout: int = 20, verify_ssl: bool = True) -> str:
    respuesta = requests.get(
        url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}, verify=verify_ssl
    )
    respuesta.raise_for_status()
    texto = trafilatura.extract(respuesta.text, favor_recall=True)
    if not texto:
        raise RuntimeError(f"No se pudo extraer texto de {url}")
    return texto


def agregar_fuente_texto(nombre: str, texto: str) -> str:
    if not texto.strip():
        raise ValueError("El texto extraído está vacío.")

    codigo = _slug(nombre)
    todos = listar_paises()

    codigo_final = codigo
    contador = 2
    while codigo_final in todos:
        codigo_final = f"{codigo}_{contador}"
        contador += 1

    _bucket().blob(f"raw/{codigo_final}.txt").upload_from_string(
        texto, content_type="text/plain; charset=utf-8"
    )

    manifest_nube = _cargar_manifest_nube()
    manifest_nube[codigo_final] = nombre
    _guardar_manifest_nube(manifest_nube)

    return codigo_final


def eliminar_fuente(codigo: str):
    manifest_nube = _cargar_manifest_nube()
    if codigo not in manifest_nube:
        raise ValueError(
            f"'{codigo}' no se puede eliminar (es uno de los países base, o no existe)."
        )

    blob = _bucket().blob(f"raw/{codigo}.txt")
    if blob.exists():
        blob.delete()

    del manifest_nube[codigo]
    _guardar_manifest_nube(manifest_nube)
