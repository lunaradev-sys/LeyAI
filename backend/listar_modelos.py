"""Prueba de verdad cuáles modelos de embeddings sirven en tu cuenta.

Aparecer en la lista de modelos no garantiza que se puedan llamar, así que
este script le manda un texto corto a cada candidato y reporta el resultado.

    python listar_modelos.py            # prueba los candidatos por nombre
    python listar_modelos.py --todos    # muestra además la lista completa
"""

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

PISTAS = ("embed", "bge", "e5", "gte", "retrieval")
EXCLUIR = ("rerank", "vlm", "-vl-")  # reordenadores y modelos de imagen

TEXTO_PRUEBA = "requisitos para constituir una cooperativa"


def probar(cliente: OpenAI, modelo: str):
    """Devuelve (sirve, detalle)."""
    for extra in ({"input_type": "query", "truncate": "END"}, {"input_type": "query"}, {}):
        try:
            respuesta = cliente.embeddings.create(
                model=modelo,
                input=[TEXTO_PRUEBA],
                encoding_format="float",
                extra_body=extra,
            )
            dimension = len(respuesta.data[0].embedding)
            nota = "" if extra else " (sin input_type)"
            return True, f"{dimension} dimensiones{nota}"
        except Exception as e:
            mensaje = str(e)
            # Si se queja del input_type probamos la siguiente variante.
            if "input_type" in mensaje or "extra" in mensaje.lower():
                continue
            corto = mensaje.split("\n")[0]
            return False, corto[:120]
    return False, "no aceptó ninguna variante de parámetros"


def main():
    cliente = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.getenv("NVIDIA_API_KEY"),
        timeout=60.0,
    )

    todos = sorted(modelo.id for modelo in cliente.models.list().data)
    candidatos = [
        m for m in todos
        if any(p in m.lower() for p in PISTAS) and not any(x in m.lower() for x in EXCLUIR)
    ]

    print(f"Modelos en la cuenta: {len(todos)}. Candidatos a embeddings: {len(candidatos)}\n")
    print("Probando cada uno con una llamada real…\n")

    sirven = []
    for modelo in candidatos:
        funciona, detalle = probar(cliente, modelo)
        marca = "OK   " if funciona else "falla"
        print(f"  [{marca}] {modelo:<50} {detalle}")
        if funciona:
            sirven.append((modelo, detalle))

    print()
    if sirven:
        print("Sirven estos. Pon uno en el .env como NVIDIA_EMBEDDING_MODEL=<nombre>\n")
        for modelo, detalle in sirven:
            print(f"  {modelo}   ({detalle})")
    else:
        print("Ninguno respondió. Revisa que la key del .env sea la correcta.")

    if "--todos" in sys.argv:
        print("\nLista completa de modelos de la cuenta:\n")
        for modelo in todos:
            print(f"  {modelo}")


if __name__ == "__main__":
    main()
