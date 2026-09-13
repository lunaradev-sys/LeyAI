"""Historial de conversaciones, guardado en Cloud Storage.

Cada navegador genera un identificador propio y lo manda en cada llamada. No
es un sistema de cuentas, es una llave larga imposible de adivinar, suficiente
para que tu hermano recupere sus conversaciones desde el PC y desde el celular
sin tener que registrarse.

    conversaciones/{usuario}/_indice.json   lista de conversaciones
    conversaciones/{usuario}/{id}.json      cada conversación completa
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("leyai")

PATRON_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
MAX_MENSAJES = 200


def validar_id(valor: str, campo: str) -> str:
    """Evita que alguien mande '../otro_usuario' y se pasee por el bucket."""
    if not valor or not PATRON_ID.fullmatch(valor):
        raise ValueError(f"{campo} inválido")
    return valor


def _bucket():
    from search import _bucket as obtener_bucket
    return obtener_bucket()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ruta_indice(usuario: str) -> str:
    return f"conversaciones/{usuario}/_indice.json"


def _ruta_conversacion(usuario: str, conversacion_id: str) -> str:
    return f"conversaciones/{usuario}/{conversacion_id}.json"


def _leer_json(ruta: str, por_defecto):
    blob = _bucket().blob(ruta)
    if not blob.exists():
        return por_defecto
    try:
        return json.loads(blob.download_as_text())
    except json.JSONDecodeError:
        logger.warning("JSON corrupto en %s", ruta)
        return por_defecto


def _escribir_json(ruta: str, datos):
    _bucket().blob(ruta).upload_from_string(
        json.dumps(datos, ensure_ascii=False), content_type="application/json"
    )


def listar(usuario: str) -> list[dict]:
    validar_id(usuario, "usuario")
    indice = _leer_json(_ruta_indice(usuario), [])
    return sorted(indice, key=lambda c: c.get("actualizada", ""), reverse=True)


def obtener(usuario: str, conversacion_id: str) -> dict | None:
    validar_id(usuario, "usuario")
    validar_id(conversacion_id, "conversacion_id")
    return _leer_json(_ruta_conversacion(usuario, conversacion_id), None)


def crear(usuario: str, titulo: str) -> dict:
    validar_id(usuario, "usuario")
    conversacion = {
        "id": uuid.uuid4().hex,
        "titulo": (titulo or "Nueva conversación").strip()[:70],
        "creada": _ahora(),
        "actualizada": _ahora(),
        "mensajes": [],
    }
    return conversacion


def guardar(usuario: str, conversacion: dict):
    validar_id(usuario, "usuario")
    validar_id(conversacion["id"], "conversacion_id")

    conversacion["actualizada"] = _ahora()
    conversacion["mensajes"] = conversacion["mensajes"][-MAX_MENSAJES:]
    _escribir_json(_ruta_conversacion(usuario, conversacion["id"]), conversacion)

    indice = _leer_json(_ruta_indice(usuario), [])
    resumen = {
        "id": conversacion["id"],
        "titulo": conversacion["titulo"],
        "creada": conversacion["creada"],
        "actualizada": conversacion["actualizada"],
        "mensajes": len(conversacion["mensajes"]),
    }
    indice = [c for c in indice if c.get("id") != conversacion["id"]]
    indice.append(resumen)
    _escribir_json(_ruta_indice(usuario), indice)


def eliminar(usuario: str, conversacion_id: str):
    validar_id(usuario, "usuario")
    validar_id(conversacion_id, "conversacion_id")

    blob = _bucket().blob(_ruta_conversacion(usuario, conversacion_id))
    if blob.exists():
        blob.delete()

    indice = [c for c in _leer_json(_ruta_indice(usuario), []) if c.get("id") != conversacion_id]
    _escribir_json(_ruta_indice(usuario), indice)


def renombrar(usuario: str, conversacion_id: str, titulo: str):
    conversacion = obtener(usuario, conversacion_id)
    if conversacion is None:
        raise ValueError("La conversación no existe")
    conversacion["titulo"] = (titulo or "").strip()[:70] or conversacion["titulo"]
    guardar(usuario, conversacion)
    return conversacion
