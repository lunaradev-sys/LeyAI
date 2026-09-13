"""Cliente de embeddings de NVIDIA.

Los embeddings convierten un texto en un vector de números. Dos textos que
hablan de lo mismo quedan con vectores parecidos, y eso es lo que permite
buscar por significado en vez de por palabra exacta.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv(override=True)

logger = logging.getLogger("leyai")

# Multilingüe, necesario porque las leyes están en español, inglés, portugués,
# alemán, sueco, finlandés, francés e italiano.
MODELO_EMBEDDING = os.getenv("NVIDIA_EMBEDDING_MODEL", "baai/bge-m3")

# Si el modelo de arriba no está disponible en tu cuenta, prueba estos.
MODELOS_ALTERNATIVOS = [
    "baai/bge-m3",
    "nvidia/llama-3.2-nv-embedqa-1b-v2",
    "nvidia/nv-embedqa-e5-v5",
    "nvidia/nv-embed-v1",
]

TAMANO_LOTE = 24

_cliente = None


def _client() -> AsyncOpenAI:
    global _cliente
    if _cliente is None:
        _cliente = AsyncOpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=os.getenv("NVIDIA_API_KEY"),
            timeout=90.0,
        )
    return _cliente


async def _embeber_lote(textos: list[str], tipo: str) -> list[list[float]]:
    respuesta = await _client().embeddings.create(
        model=MODELO_EMBEDDING,
        input=textos,
        encoding_format="float",
        # NVIDIA distingue entre el texto que se guarda ("passage") y la
        # pregunta que se hace ("query"). Usar el tipo correcto mejora bastante
        # la calidad de la búsqueda.
        extra_body={"input_type": tipo, "truncate": "END"},
    )
    ordenados = sorted(respuesta.data, key=lambda d: d.index)
    return [d.embedding for d in ordenados]


async def embeber(textos: list[str], tipo: str = "passage", reintentos: int = 4) -> list[list[float]]:
    """Convierte una lista de textos en vectores, de a lotes y con reintentos."""
    if not textos:
        return []

    vectores: list[list[float]] = []
    total_lotes = (len(textos) + TAMANO_LOTE - 1) // TAMANO_LOTE

    for numero, inicio in enumerate(range(0, len(textos), TAMANO_LOTE), start=1):
        lote = textos[inicio:inicio + TAMANO_LOTE]
        for intento in range(reintentos):
            try:
                vectores.extend(await _embeber_lote(lote, tipo))
                break
            except Exception as e:
                if intento == reintentos - 1:
                    raise
                espera = 2 ** intento
                logger.warning(
                    "Lote %d/%d falló, reintentando en %ds (%s)",
                    numero, total_lotes, espera, e,
                )
                await asyncio.sleep(espera)

    return vectores


async def embeber_consulta(texto: str) -> list[float]:
    """Vector de una pregunta del usuario."""
    resultado = await embeber([texto], tipo="query")
    return resultado[0]


async def probar_modelo() -> int:
    """Verifica que el modelo responde. Devuelve la dimensión del vector."""
    vector = await embeber_consulta("prueba de conexión")
    return len(vector)


async def listar_modelos() -> list[str]:
    """Todos los modelos disponibles hoy en la cuenta."""
    respuesta = await _client().models.list()
    return sorted(modelo.id for modelo in respuesta.data)


async def modelos_de_embedding() -> list[str]:
    """Los que parecen ser de embeddings, por nombre."""
    pistas = ("embed", "retrieval", "bge", "e5", "gte")
    return [m for m in await listar_modelos() if any(p in m.lower() for p in pistas)]
