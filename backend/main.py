import asyncio
import json
import logging
import os
import tempfile
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import APIError
from pydantic import BaseModel, Field, ValidationError

import historial
import indice
from extractor import extraer_texto
from llm import (
    chat_stream,
    comparar_con_pais,
    comparar_entre_paises,
    identificar_tema,
    resumir_pais,
    titular_conversacion,
)
from search import (
    agregar_fuente_texto,
    cargar_fuente,
    eliminar_fuente,
    extraer_url,
    listar_paises,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("leyai")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ley-ai.vercel.app", "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https://ley-ai-.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXTENSIONES_PERMITIDAS = {".pdf", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_PAISES_COMPARAR = 15
LLAMADAS_EN_PARALELO = 3


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

async def _guardar_subida(archivo: UploadFile) -> str:
    """Guarda la subida en disco validando extensión y tamaño. Devuelve el texto."""
    extension = os.path.splitext(archivo.filename or "")[1].lower()
    if extension not in EXTENSIONES_PERMITIDAS:
        raise HTTPException(status_code=400, detail=f"Formato no soportado ({extension}). Solo PDF o DOCX.")

    tamano = 0
    with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
        ruta_temporal = tmp.name
        while True:
            trozo = await archivo.read(1024 * 1024)
            if not trozo:
                break
            tamano += len(trozo)
            if tamano > MAX_FILE_SIZE:
                tmp.close()
                os.remove(ruta_temporal)
                raise HTTPException(
                    status_code=413,
                    detail=f"El archivo supera {MAX_FILE_SIZE // (1024 * 1024)} MB.",
                )
            tmp.write(trozo)

    try:
        return extraer_texto(ruta_temporal)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Error extrayendo texto de %s", archivo.filename)
        raise HTTPException(status_code=400, detail="No se pudo leer el archivo, puede estar dañado.")
    finally:
        os.remove(ruta_temporal)


async def _texto_relevante(codigo: str, nombre: str) -> str:
    """Material de un país para resumir o comparar.

    Usa el índice semántico, que recorre la ley completa. Si el índice no
    existe todavía, cae al método antiguo de cortar por el comienzo.
    """
    try:
        fragmentos = await indice.fragmentos_de_pais(codigo)
        if fragmentos:
            return indice.armar_contexto(fragmentos)
    except Exception as e:
        logger.warning("Sin índice para %s (%s), se usa el texto crudo", codigo, e)
    return cargar_fuente(codigo)


# ---------------------------------------------------------------------------
# Básicos
# ---------------------------------------------------------------------------

@app.get("/")
def read_root():
    return {"mensaje": "LeyAI backend funcionando"}


@app.get("/paises")
def obtener_paises():
    return listar_paises()


@app.get("/estado")
def estado():
    """Diagnóstico rápido, sirve para saber si el índice está al día."""
    paises = listar_paises()
    indexados = indice.paises_indexados()
    return {
        "paises": len(paises),
        "indexados": len(indexados),
        "sin_indexar": sorted(nombre for codigo, nombre in paises.items() if codigo not in indexados),
        "indice_listo": bool(indexados),
    }


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class PeticionChat(BaseModel):
    usuario: str
    mensaje: str = Field(min_length=1, max_length=4000)
    conversacion_id: Optional[str] = None
    paises: List[str] = []


def _sse(tipo: str, **datos) -> str:
    return f"data: {json.dumps({'tipo': tipo, **datos}, ensure_ascii=False)}\n\n"


@app.post("/chat")
async def chat(peticion: PeticionChat):
    try:
        historial.validar_id(peticion.usuario, "usuario")
        if peticion.conversacion_id:
            historial.validar_id(peticion.conversacion_id, "conversacion_id")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not indice.hay_indice():
        raise HTTPException(
            status_code=503,
            detail="El índice de leyes no está construido todavía. Corre construir_indice.py.",
        )

    conocidos = set(listar_paises())
    codigos = [c for c in peticion.paises if c in conocidos]

    conversacion = None
    if peticion.conversacion_id:
        conversacion = historial.obtener(peticion.usuario, peticion.conversacion_id)
    if conversacion is None:
        conversacion = historial.crear(peticion.usuario, peticion.mensaje)
        es_nueva = True
    else:
        es_nueva = False

    mensajes_previos = list(conversacion["mensajes"])

    async def generar():
        try:
            fragmentos = await indice.buscar(peticion.mensaje, codigos=codigos or None)
        except Exception as e:
            logger.exception("Falló la búsqueda de fragmentos")
            yield _sse("error", detalle=f"No se pudo buscar en las leyes. ({e})")
            return

        fuentes = [
            {"pais": f["pais"], "etiqueta": f.get("etiqueta"), "codigo": f["codigo"]}
            for f in fragmentos
        ]
        yield _sse("inicio", conversacion_id=conversacion["id"], fuentes=fuentes)

        respuesta = ""
        try:
            contexto = indice.armar_contexto(fragmentos)
            async for delta in chat_stream(mensajes_previos, peticion.mensaje, contexto):
                respuesta += delta
                yield _sse("delta", texto=delta)
        except APIError as e:
            logger.exception("Error llamando a NVIDIA")
            yield _sse("error", detalle=f"Error al conectar con NVIDIA. ({e})")
            return
        except Exception as e:
            logger.exception("Error generando la respuesta")
            yield _sse("error", detalle=f"Ocurrió un error generando la respuesta. ({e})")
            return

        conversacion["mensajes"].append({"rol": "usuario", "contenido": peticion.mensaje})
        conversacion["mensajes"].append({
            "rol": "asistente",
            "contenido": respuesta,
            "fuentes": fuentes,
        })

        if es_nueva:
            conversacion["titulo"] = await titular_conversacion(peticion.mensaje)

        try:
            historial.guardar(peticion.usuario, conversacion)
        except Exception:
            logger.exception("No se pudo guardar la conversación")

        yield _sse("fin", conversacion_id=conversacion["id"], titulo=conversacion["titulo"])

    return StreamingResponse(
        generar(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Conversaciones
# ---------------------------------------------------------------------------

class Renombrar(BaseModel):
    titulo: str


@app.get("/conversaciones/{usuario}")
def listar_conversaciones(usuario: str):
    try:
        return historial.listar(usuario)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/conversaciones/{usuario}/{conversacion_id}")
def obtener_conversacion(usuario: str, conversacion_id: str):
    try:
        conversacion = historial.obtener(usuario, conversacion_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if conversacion is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return conversacion


@app.patch("/conversaciones/{usuario}/{conversacion_id}")
def renombrar_conversacion(usuario: str, conversacion_id: str, datos: Renombrar):
    try:
        return historial.renombrar(usuario, conversacion_id, datos.titulo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/conversaciones/{usuario}/{conversacion_id}")
def eliminar_conversacion(usuario: str, conversacion_id: str):
    try:
        historial.eliminar(usuario, conversacion_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"mensaje": "Conversación eliminada"}


# ---------------------------------------------------------------------------
# Comparar
# ---------------------------------------------------------------------------

@app.post("/comparar")
async def comparar(
    paises: List[str] = Form(...),
    archivo: Optional[UploadFile] = File(None),
    comparar_entre_si: bool = Form(False),
):
    if not paises:
        raise HTTPException(status_code=400, detail="Elige al menos un país.")
    if len(paises) > MAX_PAISES_COMPARAR:
        raise HTTPException(
            status_code=400,
            detail=f"Máximo {MAX_PAISES_COMPARAR} países por consulta.",
        )

    nombres_paises = listar_paises()
    for pais in paises:
        if pais not in nombres_paises:
            raise HTTPException(status_code=400, detail=f"País no reconocido: {pais}")

    texto_propio = None
    analisis_propio = None

    if archivo is not None:
        logger.info("Recibiendo archivo, %s", archivo.filename)
        texto_propio = await _guardar_subida(archivo)

        if not texto_propio.strip():
            raise HTTPException(status_code=422, detail="No se pudo extraer texto del archivo (¿PDF escaneado?).")

        try:
            analisis_propio = await identificar_tema(texto_propio)
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="El modelo no devolvió un JSON válido, intenta de nuevo.")
        except ValidationError:
            raise HTTPException(status_code=502, detail="El modelo devolvió una respuesta con formato inesperado.")
        except APIError as e:
            logger.exception("Error llamando a NVIDIA")
            raise HTTPException(status_code=502, detail=f"Error al conectar con NVIDIA. ({e})")

    limite = asyncio.Semaphore(LLAMADAS_EN_PARALELO)

    async def con_limite(corrutina):
        async with limite:
            return await corrutina

    try:
        if texto_propio:
            async def comparar_uno(pais: str):
                nombre = nombres_paises[pais]
                material = await _texto_relevante(pais, nombre)
                return {
                    "pais": nombre,
                    "comparacion": await comparar_con_pais(texto_propio, nombre, material),
                }

            resultados = await asyncio.gather(*(con_limite(comparar_uno(p)) for p in paises))
            return {"analisis": analisis_propio, "resultados": list(resultados), "comparacion_grupal": None}

        if comparar_entre_si and len(paises) >= 2:
            materiales = await asyncio.gather(
                *(con_limite(_texto_relevante(p, nombres_paises[p])) for p in paises)
            )
            textos_paises = {nombres_paises[p]: m for p, m in zip(paises, materiales)}
            comparacion = await comparar_entre_paises(textos_paises)
            return {
                "analisis": None,
                "resultados": None,
                "comparacion_grupal": {
                    "paises": list(textos_paises.keys()),
                    "diferencias": comparacion["diferencias"],
                },
            }

        async def resumir_uno(pais: str):
            nombre = nombres_paises[pais]
            material = await _texto_relevante(pais, nombre)
            return {"pais": nombre, "resumen": await resumir_pais(nombre, material)}

        resultados = await asyncio.gather(*(con_limite(resumir_uno(p)) for p in paises))
        return {"analisis": None, "resultados": list(resultados), "comparacion_grupal": None}

    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="El modelo no devolvió un JSON válido, intenta de nuevo.")
    except APIError as e:
        logger.exception("Error llamando a NVIDIA")
        raise HTTPException(status_code=502, detail=f"Error al conectar con NVIDIA. ({e})")


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------

@app.post("/fuentes")
async def agregar_fuente(
    nombre_pais: str = Form(...),
    url: Optional[str] = Form(None),
    archivo: Optional[UploadFile] = File(None),
):
    if not url and archivo is None:
        raise HTTPException(status_code=400, detail="Debes indicar una URL o subir un archivo.")
    if url and archivo is not None:
        raise HTTPException(status_code=400, detail="Elige solo una opción, URL o archivo, no ambas.")

    if archivo is not None:
        texto = await _guardar_subida(archivo)
    else:
        try:
            texto = extraer_url(url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"No se pudo extraer texto de esa URL. ({e})")

    if len(texto.strip()) < 1000:
        raise HTTPException(
            status_code=422,
            detail=(
                "La fuente entregó muy poco texto, probablemente la página necesita "
                "JavaScript o bloqueó la descarga. Prueba subiendo el PDF de la ley."
            ),
        )

    codigo = agregar_fuente_texto(nombre_pais, texto)

    try:
        await indice.agregar_pais_al_indice(codigo, nombre_pais, texto)
        indexado = True
    except Exception:
        logger.exception("No se pudo indexar %s", codigo)
        indexado = False

    return {"codigo": codigo, "nombre": nombre_pais, "indexado": indexado}


@app.delete("/fuentes/{codigo}")
def eliminar_fuente_endpoint(codigo: str):
    try:
        eliminar_fuente(codigo)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        indice.quitar_pais_del_indice(codigo)
    except Exception:
        logger.exception("No se pudo quitar %s del índice", codigo)

    return {"mensaje": f"{codigo} eliminado"}
