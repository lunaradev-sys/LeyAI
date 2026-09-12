import os
import tempfile
import json
import logging
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import APIError
from pydantic import ValidationError
from extractor import extraer_texto
from llm import identificar_tema, resumir_pais, comparar_con_pais, comparar_entre_paises
from search import listar_paises, cargar_fuente, extraer_url, agregar_fuente_texto, eliminar_fuente

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("leyai")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ley-ai.vercel.app"],
    allow_origin_regex=r"https://ley-ai-.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXTENSIONES_PERMITIDAS = {".pdf", ".docx"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@app.get("/")
def read_root():
    return {"mensaje": "LeyAI backend funcionando"}


@app.get("/paises")
def obtener_paises():
    return listar_paises()


@app.delete("/fuentes/{codigo}")
def eliminar_fuente_endpoint(codigo: str):
    try:
        eliminar_fuente(codigo)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"mensaje": f"{codigo} eliminado"}


@app.post("/comparar")
async def comparar(
    paises: List[str] = Form(...),
    archivo: Optional[UploadFile] = File(None),
    comparar_entre_si: bool = Form(False),
):
    if not (1 <= len(paises) <= 3):
        raise HTTPException(status_code=400, detail="Elige entre 1 y 3 países.")

    nombres_paises = listar_paises()
    for pais in paises:
        if pais not in nombres_paises:
            raise HTTPException(status_code=400, detail=f"País no reconocido: {pais}")

    texto_propio = None
    analisis_propio = None

    if archivo is not None:
        extension = os.path.splitext(archivo.filename)[1].lower()
        if extension not in EXTENSIONES_PERMITIDAS:
            raise HTTPException(status_code=400, detail=f"Formato no soportado ({extension}). Solo PDF o DOCX.")

        logger.info("Recibiendo archivo, %s", archivo.filename)

        tamano = 0
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
            ruta_temporal = tmp.name
            while True:
                chunk = await archivo.read(1024 * 1024)
                if not chunk:
                    break
                tamano += len(chunk)
                if tamano > MAX_FILE_SIZE:
                    tmp.close()
                    os.remove(ruta_temporal)
                    raise HTTPException(status_code=413, detail=f"El archivo supera {MAX_FILE_SIZE // (1024*1024)} MB.")
                tmp.write(chunk)

        try:
            texto_propio = extraer_texto(ruta_temporal)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception:
            logger.exception("Error extrayendo texto de %s", archivo.filename)
            raise HTTPException(status_code=400, detail="No se pudo leer el archivo, puede estar dañado.")
        finally:
            os.remove(ruta_temporal)

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

    try:
        if texto_propio:
            resultados = []
            for pais in paises:
                texto_pais = cargar_fuente(pais)
                nombre_pais = nombres_paises[pais]
                resultados.append({
                    "pais": nombre_pais,
                    "comparacion": await comparar_con_pais(texto_propio, nombre_pais, texto_pais)
                })
            return {"analisis": analisis_propio, "resultados": resultados, "comparacion_grupal": None}

        if comparar_entre_si and len(paises) >= 2:
            textos_paises = {nombres_paises[p]: cargar_fuente(p) for p in paises}
            comparacion = await comparar_entre_paises(textos_paises)
            return {
                "analisis": None,
                "resultados": None,
                "comparacion_grupal": {"paises": list(textos_paises.keys()), "diferencias": comparacion["diferencias"]},
            }

        resultados = []
        for pais in paises:
            texto_pais = cargar_fuente(pais)
            nombre_pais = nombres_paises[pais]
            resultados.append({"pais": nombre_pais, "resumen": await resumir_pais(nombre_pais, texto_pais)})
        return {"analisis": None, "resultados": resultados, "comparacion_grupal": None}

    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="El modelo no devolvió un JSON válido, intenta de nuevo.")
    except APIError as e:
        logger.exception("Error llamando a NVIDIA")
        raise HTTPException(status_code=502, detail=f"Error al conectar con NVIDIA. ({e})")
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
        extension = os.path.splitext(archivo.filename)[1].lower()
        if extension not in EXTENSIONES_PERMITIDAS:
            raise HTTPException(status_code=400, detail=f"Formato no soportado ({extension}). Solo PDF o DOCX.")

        tamano = 0
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
            ruta_temporal = tmp.name
            while True:
                chunk = await archivo.read(1024 * 1024)
                if not chunk:
                    break
                tamano += len(chunk)
                if tamano > MAX_FILE_SIZE:
                    tmp.close()
                    os.remove(ruta_temporal)
                    raise HTTPException(status_code=413, detail=f"El archivo supera {MAX_FILE_SIZE // (1024*1024)} MB.")
                tmp.write(chunk)

        try:
            texto = extraer_texto(ruta_temporal)
        except Exception:
            raise HTTPException(status_code=400, detail="No se pudo leer el archivo, puede estar dañado.")
        finally:
            os.remove(ruta_temporal)
    else:
        try:
            texto = extraer_url(url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"No se pudo extraer texto de esa URL. ({e})")

    if not texto.strip():
        raise HTTPException(status_code=422, detail="No se encontró texto en la fuente.")

    codigo = agregar_fuente_texto(nombre_pais, texto)
    return {"codigo": codigo, "nombre": nombre_pais}