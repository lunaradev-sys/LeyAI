import os
import json
import logging
from dotenv import load_dotenv
from openai import AsyncOpenAI
from models import AnalisisLey

load_dotenv(override=True)

logger = logging.getLogger("leyai")

client = AsyncOpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY"),
    timeout=30.0
)

MODELO_RAPIDO = "deepseek-ai/deepseek-v4-flash-0731"


async def identificar_tema(texto_ley: str) -> AnalisisLey:
    logger.info("Enviando texto a NVIDIA (%d caracteres)", len(texto_ley))
    respuesta = await client.chat.completions.create(
        model=MODELO_RAPIDO,
        messages=[
            {
                "role": "user",
                "content": (
                    "Analiza el siguiente texto de una ley y responde SOLO con JSON válido, "
                    "sin texto adicional, con estos campos, pais, tema, articulos_clave "
                    "(lista breve con los artículos o puntos más relevantes).\n\n"
                    f"Texto de la ley:\n{texto_ley[:4000]}"
                )
            }
        ],
        temperature=0.2,
        max_tokens=800,
        extra_body={"chat_template_kwargs": {"thinking": False}},
    )

    contenido = respuesta.choices[0].message.content
    logger.info("Respuesta cruda del modelo: %s", contenido[:300])

    datos = _extraer_json(contenido)
    analisis = AnalisisLey.model_validate(datos)
    logger.info("Análisis recibido, país=%s tema=%s", analisis.pais, analisis.tema)
    return analisis


def _extraer_json(contenido: str) -> dict:
    inicio = contenido.find("{")
    fin = contenido.rfind("}")
    if inicio == -1 or fin == -1:
        raise json.JSONDecodeError("No se encontró JSON en la respuesta", contenido, 0)
    return json.loads(contenido[inicio:fin + 1])


async def resumir_pais(nombre_pais: str, texto_pais: str) -> dict:
    respuesta = await client.chat.completions.create(
        model=MODELO_RAPIDO,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Explica en español, en detalle, la ley de cooperativas de {nombre_pais}. "
                    "Responde SOLO con JSON válido, con estos campos, cada uno debe ser un "
                    "resumen completo de 2 a 3 párrafos (no frases sueltas), explicando bien "
                    "el contenido y sin omitir detalles importantes, "
                    "requisitos_constitucion, gobierno, derechos_deberes_socios, "
                    "distribucion_excedentes, disolucion_liquidacion. "
                    "Basado solo en el texto, sin inventar información.\n\n"
                    f"TEXTO:\n{texto_pais[:20000]}"
                )
            }
        ],
        temperature=0.2,
        max_tokens=3000,
        extra_body={"chat_template_kwargs": {"thinking": False}},
    )
    return _extraer_json(respuesta.choices[0].message.content)


async def comparar_con_pais(texto_propio: str, nombre_pais: str, texto_pais: str) -> dict:
    respuesta = await client.chat.completions.create(
        model=MODELO_RAPIDO,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Compara la LEY SUBIDA con la ley de cooperativas de {nombre_pais}. "
                    "Responde SOLO con JSON válido, con un campo 'diferencias' que sea "
                    "una lista de objetos con 'tema' y 'detalle', señalando las "
                    "diferencias más relevantes entre ambas legislaciones.\n\n"
                    f"LEY SUBIDA:\n{texto_propio[:8000]}\n\n"
                    f"LEY DE {nombre_pais.upper()}:\n{texto_pais[:20000]}"
                )
            }
        ],
        temperature=0.2,
        max_tokens=1500,
        extra_body={"chat_template_kwargs": {"thinking": False}},
    )
    return _extraer_json(respuesta.choices[0].message.content)


async def comparar_entre_paises(paises_textos: dict) -> dict:
    bloques = "\n\n".join(
        f"LEY DE {nombre.upper()}:\n{texto[:15000]}"
        for nombre, texto in paises_textos.items()
    )
    respuesta = await client.chat.completions.create(
        model=MODELO_RAPIDO,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Compara las leyes de cooperativas de estos países entre sí, "
                    f"{', '.join(paises_textos.keys())}. "
                    "Responde SOLO con JSON válido, con un campo 'diferencias' que sea "
                    "una lista de objetos con 'tema' y 'detalle'. El 'detalle' debe explicar "
                    "cómo trata ese tema cada país por separado, sé específico y detallado.\n\n"
                    f"{bloques}"
                )
            }
        ],
        temperature=0.2,
        max_tokens=2500,
        extra_body={"chat_template_kwargs": {"thinking": False}},
    )
    return _extraer_json(respuesta.choices[0].message.content)