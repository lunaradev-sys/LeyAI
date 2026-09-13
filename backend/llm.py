import os
import json
import logging
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from openai import AsyncOpenAI

from models import AnalisisLey

load_dotenv(override=True)

logger = logging.getLogger("leyai")

client = AsyncOpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY"),
    timeout=120.0,
)

MODELO_RAPIDO = os.getenv("NVIDIA_MODEL", "deepseek-ai/deepseek-v4-flash-0731")
MODELO_CHAT = os.getenv("NVIDIA_CHAT_MODEL", MODELO_RAPIDO)

SIN_PENSAR = {"chat_template_kwargs": {"thinking": False}}


def _extraer_json(contenido: str) -> dict:
    inicio = contenido.find("{")
    fin = contenido.rfind("}")
    if inicio == -1 or fin == -1:
        raise json.JSONDecodeError("No se encontró JSON en la respuesta", contenido, 0)
    return json.loads(contenido[inicio:fin + 1])


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

SISTEMA_CHAT = """Eres LeyAI, un asistente experto en legislación de cooperativas de distintos países.

Reglas que debes cumplir siempre:

1. Responde SIEMPRE en español, aunque los textos de las leyes estén en inglés, portugués, alemán, sueco, finlandés, francés o italiano. Traduce lo que necesites citar.
2. Basa tu respuesta únicamente en los EXTRACTOS DE LEYES que te entrego. No inventes artículos, cifras ni requisitos.
3. Cuando afirmes algo, di de qué país es y, si el extracto lo indica, de qué artículo. Por ejemplo, "en Chile, el artículo 11 exige…".
4. Si los extractos no alcanzan para responder, dilo con claridad y sugiere qué país o qué tema conviene consultar. No rellenes con conocimiento general.
5. Si te piden comparar, organiza la respuesta por temas y muestra cómo trata cada país ese tema, no país por país en bloques sueltos.
6. Escribe en prosa clara, usa listas o tablas solo cuando ayuden de verdad. Nada de relleno ni de repetir la pregunta.
7. Recuerda que quien pregunta no es abogado. Explica los términos técnicos la primera vez que los uses."""


def _mensajes_chat(historial: list[dict], pregunta: str, contexto: str) -> list[dict]:
    mensajes = [{"role": "system", "content": SISTEMA_CHAT}]

    # Solo los últimos intercambios, para no inflar el contexto.
    for mensaje in historial[-8:]:
        rol = "assistant" if mensaje.get("rol") == "asistente" else "user"
        mensajes.append({"role": rol, "content": mensaje.get("contenido", "")})

    if contexto:
        contenido = (
            "EXTRACTOS DE LEYES relevantes para la pregunta:\n\n"
            f"{contexto}\n\n"
            "---\n"
            f"PREGUNTA: {pregunta}"
        )
    else:
        contenido = (
            "No se encontraron extractos relevantes en las leyes cargadas.\n\n"
            f"PREGUNTA: {pregunta}\n\n"
            "Dile al usuario que no hay material suficiente y sugiérele cómo reformular."
        )

    mensajes.append({"role": "user", "content": contenido})
    return mensajes


async def chat_stream(historial: list[dict], pregunta: str, contexto: str) -> AsyncIterator[str]:
    """Devuelve la respuesta en pedazos, a medida que el modelo la genera."""
    flujo = await client.chat.completions.create(
        model=MODELO_CHAT,
        messages=_mensajes_chat(historial, pregunta, contexto),
        temperature=0.3,
        max_tokens=3000,
        stream=True,
        extra_body=SIN_PENSAR,
    )

    async for pedazo in flujo:
        if not pedazo.choices:
            continue
        delta = pedazo.choices[0].delta
        if delta and delta.content:
            yield delta.content


async def titular_conversacion(pregunta: str) -> str:
    """Título corto para la lista lateral de conversaciones."""
    try:
        respuesta = await client.chat.completions.create(
            model=MODELO_RAPIDO,
            messages=[{
                "role": "user",
                "content": (
                    "Resume esta consulta en un título de máximo 6 palabras, en español, "
                    "sin comillas ni punto final. Responde solo con el título.\n\n"
                    f"{pregunta[:500]}"
                ),
            }],
            temperature=0.2,
            max_tokens=40,
            extra_body=SIN_PENSAR,
        )
        titulo = (respuesta.choices[0].message.content or "").strip().strip('"')
        return titulo[:70] or pregunta[:70]
    except Exception:
        logger.warning("No se pudo generar el título, se usa la pregunta")
        return pregunta.strip()[:70]


# ---------------------------------------------------------------------------
# Pantalla de comparar
# ---------------------------------------------------------------------------

async def identificar_tema(texto_ley: str) -> AnalisisLey:
    logger.info("Enviando texto a NVIDIA (%d caracteres)", len(texto_ley))
    respuesta = await client.chat.completions.create(
        model=MODELO_RAPIDO,
        messages=[{
            "role": "user",
            "content": (
                "Analiza el siguiente texto de una ley y responde SOLO con JSON válido, "
                "sin texto adicional, con estos campos, pais, tema, articulos_clave "
                "(lista breve con los artículos o puntos más relevantes).\n\n"
                f"Texto de la ley:\n{texto_ley[:4000]}"
            ),
        }],
        temperature=0.2,
        max_tokens=800,
        extra_body=SIN_PENSAR,
    )

    contenido = respuesta.choices[0].message.content
    logger.info("Respuesta cruda del modelo: %s", contenido[:300])

    analisis = AnalisisLey.model_validate(_extraer_json(contenido))
    logger.info("Análisis recibido, país=%s tema=%s", analisis.pais, analisis.tema)
    return analisis


async def resumir_pais(nombre_pais: str, texto_pais: str) -> dict:
    respuesta = await client.chat.completions.create(
        model=MODELO_RAPIDO,
        messages=[{
            "role": "user",
            "content": (
                f"Explica en español, en detalle, la ley de cooperativas de {nombre_pais}. "
                "Si el texto está en otro idioma, tradúcelo, la respuesta va siempre en español. "
                "Responde SOLO con JSON válido, con estos campos, cada uno debe ser un "
                "resumen completo de 2 a 3 párrafos (no frases sueltas), explicando bien "
                "el contenido y sin omitir detalles importantes, "
                "requisitos_constitucion, gobierno, derechos_deberes_socios, "
                "distribucion_excedentes, disolucion_liquidacion. "
                "Basado solo en el texto, sin inventar información. Si algún punto no "
                "aparece en el texto, dilo explícitamente en ese campo.\n\n"
                f"TEXTO:\n{texto_pais[:45000]}"
            ),
        }],
        temperature=0.2,
        max_tokens=3000,
        extra_body=SIN_PENSAR,
    )
    return _extraer_json(respuesta.choices[0].message.content)


async def comparar_con_pais(texto_propio: str, nombre_pais: str, texto_pais: str) -> dict:
    respuesta = await client.chat.completions.create(
        model=MODELO_RAPIDO,
        messages=[{
            "role": "user",
            "content": (
                f"Compara la LEY SUBIDA con la ley de cooperativas de {nombre_pais}. "
                "Responde en español, SOLO con JSON válido, con un campo 'diferencias' que sea "
                "una lista de objetos con 'tema' y 'detalle', señalando las "
                "diferencias más relevantes entre ambas legislaciones. Cita los artículos "
                "cuando el texto los indique.\n\n"
                f"LEY SUBIDA:\n{texto_propio[:12000]}\n\n"
                f"LEY DE {nombre_pais.upper()}:\n{texto_pais[:30000]}"
            ),
        }],
        temperature=0.2,
        max_tokens=2000,
        extra_body=SIN_PENSAR,
    )
    return _extraer_json(respuesta.choices[0].message.content)


async def comparar_entre_paises(paises_textos: dict) -> dict:
    # El presupuesto por país se reparte, así 15 países caben igual que 3.
    presupuesto = max(3000, 90000 // max(len(paises_textos), 1))
    bloques = "\n\n".join(
        f"LEY DE {nombre.upper()}:\n{texto[:presupuesto]}"
        for nombre, texto in paises_textos.items()
    )
    respuesta = await client.chat.completions.create(
        model=MODELO_RAPIDO,
        messages=[{
            "role": "user",
            "content": (
                f"Compara las leyes de cooperativas de estos países entre sí, "
                f"{', '.join(paises_textos.keys())}. "
                "Responde en español, SOLO con JSON válido, con un campo 'diferencias' que sea "
                "una lista de objetos con 'tema' y 'detalle'. El 'detalle' debe explicar "
                "cómo trata ese tema cada país por separado, sé específico y detallado. "
                "Organiza por temas, no por país.\n\n"
                f"{bloques}"
            ),
        }],
        temperature=0.2,
        max_tokens=4000,
        extra_body=SIN_PENSAR,
    )
    return _extraer_json(respuesta.choices[0].message.content)
