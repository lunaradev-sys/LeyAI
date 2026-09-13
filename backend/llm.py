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

SISTEMA_CHAT = """Eres LeyAI, un asistente que responde sobre legislación de cooperativas usando los extractos de ley que se te entregan.

Tu prioridad número uno es la FIDELIDAD AL TEXTO, por encima de que la respuesta suene completa o fluida. Vale mucho más una respuesta corta y exacta que una extensa con afirmaciones que la ley no hace.

Reglas obligatorias:

1. Responde SIEMPRE en español, aunque los extractos estén en inglés, portugués, alemán, sueco, finlandés, francés o italiano. Traduce de forma literal, sin adornar.
2. Usa ÚNICAMENTE los EXTRACTOS que te entrego. Cada afirmación que hagas tiene que poder rastrearse a una frase concreta de un extracto.
3. Pégate a la letra. Parafrasea lo mínimo para que se entienda y conserva tal cual los términos, plazos, porcentajes, cantidades, mayorías y condiciones. No redondees cifras, no cambies "podrá" por "deberá", no reemplaces un término legal por uno coloquial.
4. Di siempre de qué país es cada afirmación y, cuando el extracto lo indique, de qué artículo. Por ejemplo, "en Chile, el artículo 11 exige…".
5. Separa lo que dice la ley de lo que tú deduces. Si necesitas explicar algo que el texto no dice con esas palabras, ponlo aparte, empezando con "Interpretación:", y déjalo en una o dos frases. Todo lo que escribas sin esa marca debe ser lo que la ley dice.
6. Si los extractos no cubren algo, escribe "no aparece en los extractos consultados". Eso NO es lo mismo que decir que la ley no lo contempla, y no debes afirmar lo segundo nunca.
7. Prohibido rellenar con conocimiento general sobre cooperativas, sobre derecho comparado o sobre lo que suelen decir estas leyes. Si no está en los extractos, para ti no existe.
8. No traslades una regla de un país a otro ni supongas que dos países se parecen. Si solo tienes el dato de un país, responde solo por ese país.
9. Si te piden comparar, organiza por temas y muestra cómo trata cada país ese tema. Si de algún país no hay material sobre ese tema, dilo en vez de omitirlo en silencio.
10. Escribe claro y directo. Listas o tablas solo cuando ayuden de verdad. Nada de relleno, de repetir la pregunta ni de cerrar con consejos genéricos.
11. Quien pregunta no es abogado. Explica el término técnico la primera vez que lo uses, entre paréntesis y en pocas palabras."""


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
        # Temperatura baja, el modelo se queda pegado a lo que dice el texto
        # en vez de "completar" con lo que le parece razonable.
        temperature=0.1,
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
        temperature=0.1,
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
                "Si el texto está en otro idioma, tradúcelo de forma literal. "
                "Responde SOLO con JSON válido, con estos campos, cada uno debe ser un "
                "resumen completo de 2 a 3 párrafos (no frases sueltas), "
                "requisitos_constitucion, gobierno, derechos_deberes_socios, "
                "distribucion_excedentes, disolucion_liquidacion.\n\n"
                "REGLAS ESTRICTAS. Pégate a la letra del texto, conservando términos, "
                "plazos, porcentajes, cantidades y mayorías tal como aparecen. No "
                "completes con conocimiento general sobre cooperativas ni sobre lo que "
                "suelen decir estas leyes. Cita el artículo cuando el texto lo indique. "
                "Si un punto no aparece en el texto, escribe en ese campo 'no aparece en "
                "los extractos consultados', que no es lo mismo que decir que la ley no "
                "lo contempla.\n\n"
                f"TEXTO:\n{texto_pais[:45000]}"
            ),
        }],
        temperature=0.1,
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
                "REGLAS ESTRICTAS. Cada diferencia que afirmes tiene que estar respaldada "
                "por una frase concreta de alguno de los dos textos. Conserva términos, "
                "plazos, porcentajes y cantidades tal como aparecen. No inventes "
                "diferencias por simetría ni supongas lo que la otra ley diría. Si un "
                "tema aparece en un texto y en el otro no, dilo así en vez de afirmar que "
                "esa ley no lo regula.\n\n"
                f"LEY SUBIDA:\n{texto_propio[:12000]}\n\n"
                f"LEY DE {nombre_pais.upper()}:\n{texto_pais[:30000]}"
            ),
        }],
        temperature=0.1,
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
                "REGLAS ESTRICTAS. Solo puedes afirmar lo que aparece en los textos. "
                "Conserva términos, plazos, porcentajes y cantidades tal como están. No "
                "supongas que dos países se parecen ni traslades una regla de uno a otro. "
                "Si de un país no hay material sobre ese tema, escríbelo así en el "
                "detalle en vez de omitirlo o de inventar qué diría.\n\n"
                f"{bloques}"
            ),
        }],
        temperature=0.1,
        max_tokens=4000,
        extra_body=SIN_PENSAR,
    )
    return _extraer_json(respuesta.choices[0].message.content)
