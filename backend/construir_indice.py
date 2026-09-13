"""Construye el índice semántico de todas las leyes y lo sube a Cloud Storage.

Se corre a mano, desde la carpeta backend, cada vez que cambian las fuentes.

    python construir_indice.py            # construye y sube el índice
    python construir_indice.py --probar   # solo verifica que el modelo responde
    python construir_indice.py --modelos  # lista los modelos disponibles en tu cuenta
    python construir_indice.py --revisar  # solo muestra cómo quedarían los fragmentos

Necesita credenciales de Google Cloud. Si nunca las configuraste en este PC:

    gcloud auth application-default login
"""

import asyncio
import sys

import numpy as np

import embeddings
from indice import guardar_indice, trocear, vectorizar
from search import cargar_fuente, listar_paises

MINIMO_ACEPTABLE = 1000  # caracteres, menos que esto casi seguro es un scrape fallido


async def listar():
    print("Buscando modelos de embeddings disponibles en tu cuenta…\n")
    try:
        candidatos = await embeddings.modelos_de_embedding()
    except Exception as e:
        print(f"No se pudo consultar la lista de modelos: {e}")
        return

    if candidatos:
        print("Candidatos (ponlo en el .env como NVIDIA_EMBEDDING_MODEL):\n")
        for modelo in candidatos:
            print(f"  {modelo}")
    else:
        print("No se reconoció ninguno por el nombre. Lista completa:\n")
        for modelo in await embeddings.listar_modelos():
            print(f"  {modelo}")


async def probar():
    print(f"Modelo de embeddings, {embeddings.MODELO_EMBEDDING}")
    try:
        dimension = await embeddings.probar_modelo()
    except Exception as e:
        print(f"\nFALLÓ: {e}\n")
        print("Corre 'python construir_indice.py --modelos' para ver cuáles hay hoy.")
        return False
    print(f"OK, el modelo responde con vectores de {dimension} dimensiones.")
    return True


def recolectar() -> tuple[list[dict], list[str]]:
    paises = listar_paises()
    if not paises:
        raise SystemExit("No hay países en el manifiesto. Corre antes prepare_sources.py")

    fragmentos: list[dict] = []
    avisos: list[str] = []

    for codigo, nombre in paises.items():
        try:
            texto = cargar_fuente(codigo)
        except FileNotFoundError:
            avisos.append(f"{nombre} ({codigo}), no se encontró el texto, se omite")
            continue

        if len(texto.strip()) < MINIMO_ACEPTABLE:
            avisos.append(
                f"{nombre} ({codigo}), solo {len(texto.strip())} caracteres, "
                f"la fuente parece rota y se omite"
            )
            continue

        trozos = trocear(texto, codigo, nombre)
        fragmentos.extend(trozos)
        print(f"  {nombre:<16} {len(texto):>9,} car.  ->  {len(trozos):>4} fragmentos")

    return fragmentos, avisos


async def construir(solo_revisar: bool = False):
    print("Leyendo fuentes y troceando\n")
    fragmentos, avisos = recolectar()

    print(f"\nTotal, {len(fragmentos)} fragmentos de {len({f['codigo'] for f in fragmentos})} países")

    if avisos:
        print("\nAvisos:")
        for aviso in avisos:
            print(f"  - {aviso}")

    if solo_revisar:
        print("\nModo revisar, no se llamó a NVIDIA ni se subió nada.")
        if fragmentos:
            ejemplo = fragmentos[len(fragmentos) // 2]
            print(f"\nEjemplo de fragmento ({ejemplo['pais']}, {ejemplo['etiqueta']}):")
            print(ejemplo["texto"][:400] + "…")
        return

    if not fragmentos:
        raise SystemExit("No hay nada que indexar.")

    if not await probar():
        raise SystemExit(1)

    print(f"\nCalculando embeddings, esto demora unos minutos…")
    vectores = await vectorizar(fragmentos)
    print(f"Listo, matriz de {vectores.shape[0]} x {vectores.shape[1]}")

    peso = vectores.nbytes / (1024 * 1024)
    print(f"Subiendo al bucket, {peso:.1f} MB de vectores")
    guardar_indice(np.asarray(vectores), fragmentos)
    print("\nÍndice construido y subido.")


if __name__ == "__main__":
    if "--modelos" in sys.argv:
        asyncio.run(listar())
    elif "--probar" in sys.argv:
        asyncio.run(probar())
    else:
        asyncio.run(construir(solo_revisar="--revisar" in sys.argv))
