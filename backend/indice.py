"""Índice semántico de las leyes.

En vez de mandarle al modelo los primeros 20.000 caracteres de cada ley, que
era lo que se hacía antes y dejaba fuera hasta el 98% del texto, acá cada ley
se parte en fragmentos (idealmente por artículo), cada fragmento se convierte
en un vector, y al preguntar algo se buscan los fragmentos más parecidos a la
pregunta en TODO el documento.

El índice vive en Cloud Storage, en indice/vectores.npy e indice/fragmentos.json.
"""

import io
import json
import logging
import re

import numpy as np

from embeddings import embeber, embeber_consulta

logger = logging.getLogger("leyai")

BLOB_VECTORES = "indice/vectores.npy"
BLOB_FRAGMENTOS = "indice/fragmentos.json"

TAMANO_FRAGMENTO = 1400
SOLAPE = 200
MINIMO_FRAGMENTO = 40
# Los artículos muy cortos se juntan con el siguiente hasta llegar a este
# tamaño. Un fragmento de dos líneas sueltas no sirve para buscar.
OBJETIVO_MINIMO = 350

# Encabezados de artículo en los idiomas de las fuentes que tenemos.
PATRON_ARTICULO = re.compile(
    r"^[ \t]*("
    r"Art[íi]culo\s+\d+[.ºo°]*(?:\s*bis|\s*ter)?"      # español
    r"|Artigo\s+\d+[.ºo°]*"                             # portugués
    r"|Art\.\s*\d+[.ºo°]*"                              # abreviado, italiano
    r"|Article\s+\d+[A-Za-z\-]*"                        # inglés, francés
    r"|Section\s+\d+[A-Za-z\-]*"                        # inglés
    r"|§+\s*\d+[a-z]*"                                  # alemán
    r"|\d+\s*(?:kap\.|§)"                               # sueco, finlandés
    r"|Disposici[óo]n\s+(?:adicional|transitoria|final|derogatoria)\s*\d*"
    r")",
    re.IGNORECASE | re.MULTILINE,
)

# Los cinco temas que más le interesan a un análisis de ley de cooperativas.
# Se usan para armar resúmenes y comparaciones sin depender del truncado.
TEMAS_CLAVE = [
    "requisitos para constituir una cooperativa, número mínimo de socios, estatutos y registro",
    "órganos de gobierno, asamblea general, consejo de administración, derecho a voto",
    "derechos y deberes de los socios, admisión, baja y exclusión",
    "distribución de excedentes, reservas obligatorias, retorno cooperativo, capital social",
    "disolución, liquidación y destino del patrimonio remanente",
]

_indice = None
_cache_consultas: dict[str, np.ndarray] = {}


# ---------------------------------------------------------------------------
# Trocear
# ---------------------------------------------------------------------------

# El BOE español entrega el articulado como [Bloque 7: #a3-2] en vez de
# "Artículo 3 bis". Sin esto, España quedaba sin ninguna cita de artículo.
PATRON_BLOQUE_BOE = re.compile(r"\[Bloque\s+\d+:\s*#([a-z]+)(\d*)(?:-(\d+))?\]")

PREFIJOS_BOE = {
    "a": "Artículo",
    "da": "Disposición adicional",
    "dt": "Disposición transitoria",
    "df": "Disposición final",
    "dd": "Disposición derogatoria",
}


def _normalizar_fuente(texto: str) -> str:
    """Convierte marcadores propios de cada portal en encabezados legibles."""

    def reemplazo(match: re.Match) -> str:
        prefijo, numero, sufijo = match.group(1), match.group(2), match.group(3)
        etiqueta = PREFIJOS_BOE.get(prefijo)
        if not etiqueta:
            return ""  # títulos, capítulos y preámbulo, no aportan como cita
        titulo = f"{etiqueta} {numero}" if numero else etiqueta
        if sufijo:
            titulo += f"-{sufijo}"
        return f"\n{titulo}\n"

    return PATRON_BLOQUE_BOE.sub(reemplazo, texto)


def _trozos_fijos(texto: str) -> list[str]:
    """Parte un texto largo en pedazos con solape, cortando en punto seguido."""
    trozos = []
    inicio = 0
    while inicio < len(texto):
        fin = min(inicio + TAMANO_FRAGMENTO, len(texto))
        if fin < len(texto):
            corte = texto.rfind(". ", inicio + TAMANO_FRAGMENTO // 2, fin)
            if corte != -1:
                fin = corte + 1
        trozo = texto[inicio:fin].strip()
        if len(trozo) >= MINIMO_FRAGMENTO:
            trozos.append(trozo)
        if fin >= len(texto):
            break
        inicio = max(fin - SOLAPE, inicio + 1)
    return trozos


def _juntar_cortos(bloques: list[tuple[str | None, str]]) -> list[tuple[str | None, str]]:
    """Une artículos consecutivos demasiado cortos en un solo fragmento."""
    unidos: list[tuple[str | None, str]] = []
    etiquetas: list[str] = []
    acumulado: list[str] = []

    def vaciar():
        if not acumulado:
            return
        if len(etiquetas) > 1:
            etiqueta = f"{etiquetas[0]} a {etiquetas[-1]}"
        elif etiquetas:
            etiqueta = etiquetas[0]
        else:
            etiqueta = None
        unidos.append((etiqueta, "\n".join(acumulado).strip()))
        etiquetas.clear()
        acumulado.clear()

    for etiqueta, bloque in bloques:
        if not bloque:
            continue
        if len(bloque) >= OBJETIVO_MINIMO:
            vaciar()
            unidos.append((etiqueta, bloque))
            continue
        if etiqueta:
            etiquetas.append(etiqueta)
        acumulado.append(bloque)
        if sum(len(p) for p in acumulado) >= OBJETIVO_MINIMO:
            vaciar()

    vaciar()
    return unidos


def trocear(texto: str, codigo: str, nombre: str) -> list[dict]:
    """Parte una ley en fragmentos, respetando los artículos cuando se pueden detectar."""
    texto = _normalizar_fuente(texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    if not texto:
        return []

    marcas = list(PATRON_ARTICULO.finditer(texto))
    bloques: list[tuple[str | None, str]] = []

    if len(marcas) >= 5:
        preambulo = texto[:marcas[0].start()].strip()
        if len(preambulo) >= MINIMO_FRAGMENTO:
            bloques.append(("Preámbulo", preambulo))
        for i, marca in enumerate(marcas):
            fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
            etiqueta = " ".join(marca.group(1).split())
            bloques.append((etiqueta, texto[marca.start():fin].strip()))
        bloques = _juntar_cortos(bloques)
        logger.info("%s, %d artículos detectados, %d bloques", codigo, len(marcas), len(bloques))
    else:
        bloques.append((None, texto))
        logger.info("%s, sin artículos detectables, se corta por tamaño", codigo)

    fragmentos = []
    for etiqueta, bloque in bloques:
        if len(bloque) <= TAMANO_FRAGMENTO * 1.6:
            piezas = [bloque] if len(bloque) >= MINIMO_FRAGMENTO else []
        else:
            piezas = _trozos_fijos(bloque)
        for numero, pieza in enumerate(piezas, start=1):
            sufijo = f" (parte {numero})" if len(piezas) > 1 else ""
            fragmentos.append({
                "codigo": codigo,
                "pais": nombre,
                "etiqueta": f"{etiqueta}{sufijo}" if etiqueta else None,
                "texto": pieza,
                "pos": len(fragmentos),
            })

    return fragmentos


def texto_para_embeber(fragmento: dict) -> str:
    """El país y el artículo van dentro del texto para que la búsqueda los considere."""
    cabecera = fragmento["pais"]
    if fragmento.get("etiqueta"):
        cabecera += f" — {fragmento['etiqueta']}"
    return f"{cabecera}\n{fragmento['texto']}"


def _normalizar(matriz: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return (matriz / normas).astype(np.float32)


async def vectorizar(fragmentos: list[dict]) -> np.ndarray:
    textos = [texto_para_embeber(f) for f in fragmentos]
    crudos = await embeber(textos, tipo="passage")
    return _normalizar(np.asarray(crudos, dtype=np.float32))


# ---------------------------------------------------------------------------
# Guardar y cargar
# ---------------------------------------------------------------------------

def _bucket():
    from search import _bucket as obtener_bucket
    return obtener_bucket()


def guardar_indice(vectores: np.ndarray, fragmentos: list[dict]):
    global _indice
    bucket = _bucket()

    buffer = io.BytesIO()
    np.save(buffer, vectores.astype(np.float32))
    bucket.blob(BLOB_VECTORES).upload_from_string(
        buffer.getvalue(), content_type="application/octet-stream"
    )
    bucket.blob(BLOB_FRAGMENTOS).upload_from_string(
        json.dumps(fragmentos, ensure_ascii=False), content_type="application/json"
    )

    _indice = {"vectores": vectores.astype(np.float32), "fragmentos": fragmentos}
    logger.info("Índice guardado, %d fragmentos", len(fragmentos))


def cargar_indice() -> dict:
    global _indice
    if _indice is not None:
        return _indice

    bucket = _bucket()
    blob_vectores = bucket.blob(BLOB_VECTORES)
    blob_fragmentos = bucket.blob(BLOB_FRAGMENTOS)

    if not blob_vectores.exists() or not blob_fragmentos.exists():
        raise RuntimeError(
            "El índice semántico todavía no existe. Corre 'python construir_indice.py'."
        )

    vectores = np.load(io.BytesIO(blob_vectores.download_as_bytes()))
    fragmentos = json.loads(blob_fragmentos.download_as_text())

    _indice = {"vectores": vectores.astype(np.float32), "fragmentos": fragmentos}
    logger.info("Índice cargado desde el bucket, %d fragmentos", len(fragmentos))
    return _indice


def hay_indice() -> bool:
    try:
        cargar_indice()
        return True
    except Exception as e:
        logger.warning("No se pudo cargar el índice, %s", e)
        return False


def paises_indexados() -> set[str]:
    try:
        return {f["codigo"] for f in cargar_indice()["fragmentos"]}
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Buscar
# ---------------------------------------------------------------------------

async def _vector_consulta(texto: str) -> np.ndarray:
    if texto not in _cache_consultas:
        crudo = np.asarray(await embeber_consulta(texto), dtype=np.float32)
        norma = np.linalg.norm(crudo) or 1.0
        _cache_consultas[texto] = (crudo / norma).astype(np.float32)
    return _cache_consultas[texto]


async def buscar(
    pregunta: str,
    codigos: list[str] | None = None,
    k: int = 14,
    max_por_pais: int = 4,
) -> list[dict]:
    """Fragmentos más relevantes para una pregunta.

    max_por_pais evita que un país con una ley enorme, como Canadá, se coma
    todos los cupos y deje a los demás fuera de la comparación.
    """
    indice = cargar_indice()
    consulta = await _vector_consulta(pregunta)
    puntajes = indice["vectores"] @ consulta

    permitidos = set(codigos) if codigos else None
    elegidos: list[dict] = []
    por_pais: dict[str, int] = {}

    for i in np.argsort(-puntajes):
        fragmento = indice["fragmentos"][int(i)]
        if permitidos is not None and fragmento["codigo"] not in permitidos:
            continue
        if por_pais.get(fragmento["codigo"], 0) >= max_por_pais:
            continue
        por_pais[fragmento["codigo"]] = por_pais.get(fragmento["codigo"], 0) + 1
        elegidos.append({**fragmento, "puntaje": float(puntajes[int(i)])})
        if len(elegidos) >= k:
            break

    return elegidos


async def fragmentos_de_pais(codigo: str, temas: list[str] | None = None, k_por_tema: int = 3) -> list[dict]:
    """Reúne los fragmentos más relevantes de un país para varios temas.

    Reemplaza al viejo texto[:20000]. Junta material de todo el documento, no
    solo del comienzo.
    """
    indice = cargar_indice()
    temas = temas or TEMAS_CLAVE

    indices_pais = [i for i, f in enumerate(indice["fragmentos"]) if f["codigo"] == codigo]
    if not indices_pais:
        return []

    submatriz = indice["vectores"][indices_pais]
    elegidos: dict[int, float] = {}

    for tema in temas:
        consulta = await _vector_consulta(tema)
        puntajes = submatriz @ consulta
        for posicion in np.argsort(-puntajes)[:k_por_tema]:
            real = indices_pais[int(posicion)]
            puntaje = float(puntajes[int(posicion)])
            if puntaje > elegidos.get(real, -1):
                elegidos[real] = puntaje

    # En orden de documento, para que el texto que lee el modelo tenga sentido.
    ordenados = sorted(elegidos.keys(), key=lambda i: indice["fragmentos"][i]["pos"])
    return [{**indice["fragmentos"][i], "puntaje": elegidos[i]} for i in ordenados]


def armar_contexto(fragmentos: list[dict]) -> str:
    partes = []
    for f in fragmentos:
        cabecera = f["pais"]
        if f.get("etiqueta"):
            cabecera += f", {f['etiqueta']}"
        partes.append(f"[{cabecera}]\n{f['texto']}")
    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# Mantener el índice al día
# ---------------------------------------------------------------------------

async def agregar_pais_al_indice(codigo: str, nombre: str, texto: str):
    """Indexa un país recién agregado sin tener que reconstruir todo."""
    nuevos = trocear(texto, codigo, nombre)
    if not nuevos:
        raise ValueError(f"No se pudo trocear el texto de {nombre}")

    vectores_nuevos = await vectorizar(nuevos)

    try:
        indice = cargar_indice()
        fragmentos = [f for f in indice["fragmentos"] if f["codigo"] != codigo]
        conservados = [i for i, f in enumerate(indice["fragmentos"]) if f["codigo"] != codigo]
        vectores = indice["vectores"][conservados] if conservados else np.empty((0, vectores_nuevos.shape[1]), dtype=np.float32)
    except Exception:
        fragmentos, vectores = [], np.empty((0, vectores_nuevos.shape[1]), dtype=np.float32)

    guardar_indice(np.vstack([vectores, vectores_nuevos]), fragmentos + nuevos)
    logger.info("Indexado %s, %d fragmentos nuevos", nombre, len(nuevos))


def quitar_pais_del_indice(codigo: str):
    try:
        indice = cargar_indice()
    except Exception:
        return

    conservados = [i for i, f in enumerate(indice["fragmentos"]) if f["codigo"] != codigo]
    if len(conservados) == len(indice["fragmentos"]):
        return

    guardar_indice(
        indice["vectores"][conservados],
        [indice["fragmentos"][i] for i in conservados],
    )
    logger.info("Quitado %s del índice", codigo)
