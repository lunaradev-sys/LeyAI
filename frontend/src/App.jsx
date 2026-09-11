import { useState, useEffect } from 'react'
import jsPDF from 'jspdf'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

function App() {
  const [vista, setVista] = useState('comparar')

  const [paisesDisponibles, setPaisesDisponibles] = useState({})
  const [paisesSeleccionados, setPaisesSeleccionados] = useState([])
  const [archivo, setArchivo] = useState(null)
  const [compararEntreSi, setCompararEntreSi] = useState(false)
  const [estado, setEstado] = useState('inicial')
  const [resultado, setResultado] = useState(null)
  const [error, setError] = useState('')

  const [nombrePais, setNombrePais] = useState('')
  const [tipoFuente, setTipoFuente] = useState('url')
  const [urlFuente, setUrlFuente] = useState('')
  const [archivoFuente, setArchivoFuente] = useState(null)
  const [estadoAgregar, setEstadoAgregar] = useState('inicial')
  const [errorAgregar, setErrorAgregar] = useState('')

  const cargarPaises = () => {
    fetch(`${API_URL}/paises`)
      .then((r) => r.json())
      .then(setPaisesDisponibles)
      .catch(() => setError('No se pudo cargar la lista de países.'))
  }

  useEffect(() => {
    cargarPaises()
  }, [])

  const alternarPais = (codigo) => {
    setPaisesSeleccionados((actual) => {
      if (actual.includes(codigo)) return actual.filter((p) => p !== codigo)
      if (actual.length >= 3) return actual
      return [...actual, codigo]
    })
  }

  const manejarArchivo = (e) => {
    setArchivo(e.target.files[0] || null)
    setEstado('inicial')
    setResultado(null)
    setError('')
  }

  const manejarDrop = (e) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) {
      setArchivo(file)
      setEstado('inicial')
      setResultado(null)
      setError('')
    }
  }

  const comparar = async () => {
    if (paisesSeleccionados.length === 0) return
    setEstado('cargando')
    setError('')

    const formData = new FormData()
    paisesSeleccionados.forEach((p) => formData.append('paises', p))
    if (archivo) formData.append('archivo', archivo)
    if (!archivo && compararEntreSi && paisesSeleccionados.length >= 2) {
      formData.append('comparar_entre_si', 'true')
    }

    try {
      const respuesta = await fetch(`${API_URL}/comparar`, { method: 'POST', body: formData })
      if (!respuesta.ok) {
        const detalle = await respuesta.json().catch(() => null)
        throw new Error(detalle?.detail || 'Ocurrió un error al procesar la solicitud.')
      }
      const datos = await respuesta.json()
      setResultado(datos)
      setEstado('listo')
    } catch (err) {
      setError(err.message)
      setEstado('error')
    }
  }

  const agregarFuente = async () => {
    if (!nombrePais.trim()) return
    if (tipoFuente === 'url' && !urlFuente.trim()) return
    if (tipoFuente === 'archivo' && !archivoFuente) return

    setEstadoAgregar('cargando')
    setErrorAgregar('')

    const formData = new FormData()
    formData.append('nombre_pais', nombrePais.trim())
    if (tipoFuente === 'url') {
      formData.append('url', urlFuente.trim())
    } else {
      formData.append('archivo', archivoFuente)
    }

    try {
      const respuesta = await fetch(`${API_URL}/fuentes`, { method: 'POST', body: formData })
      if (!respuesta.ok) {
        const detalle = await respuesta.json().catch(() => null)
        throw new Error(detalle?.detail || 'No se pudo agregar la fuente.')
      }
      await respuesta.json()
      setEstadoAgregar('listo')
      setNombrePais('')
      setUrlFuente('')
      setArchivoFuente(null)
      cargarPaises()
    } catch (err) {
      setErrorAgregar(err.message)
      setEstadoAgregar('error')
    }
  }

  const eliminarFuente = async (codigo, nombre) => {
    if (!window.confirm(`¿Eliminar ${nombre}? Esta acción no se puede deshacer.`)) return
    try {
      const respuesta = await fetch(`${API_URL}/fuentes/${codigo}`, { method: 'DELETE' })
      if (!respuesta.ok) {
        const detalle = await respuesta.json().catch(() => null)
        throw new Error(detalle?.detail || 'No se pudo eliminar el país.')
      }
      setPaisesSeleccionados((actual) => actual.filter((p) => p !== codigo))
      cargarPaises()
    } catch (err) {
      setErrorAgregar(err.message)
    }
  }

  const descargarPDF = () => {
    if (!resultado) return
    const doc = new jsPDF()
    const margen = 15
    const anchoTexto = 180
    let y = 20

    const saltoDePagina = () => {
      if (y > 270) {
        doc.addPage()
        y = 20
      }
    }

    const agregarTitulo = (texto) => {
      doc.setFontSize(16)
      doc.setFont(undefined, 'bold')
      doc.text(texto, margen, y)
      y += 10
    }

    const agregarSubtitulo = (texto) => {
      saltoDePagina()
      doc.setFontSize(13)
      doc.setFont(undefined, 'bold')
      doc.text(texto, margen, y)
      y += 8
    }

    const agregarParrafo = (etiqueta, texto) => {
      saltoDePagina()
      doc.setFontSize(11)
      doc.setFont(undefined, 'bold')
      doc.text(etiqueta, margen, y)
      y += 6
      doc.setFont(undefined, 'normal')
      const lineas = doc.splitTextToSize(texto, anchoTexto)
      doc.text(lineas, margen, y)
      y += lineas.length * 6 + 4
    }

    if (resultado.comparacion_grupal) {
      agregarTitulo(`Diferencias entre ${resultado.comparacion_grupal.paises.join(', ')}`)
      resultado.comparacion_grupal.diferencias.forEach((d) => agregarParrafo(d.tema, d.detalle))
    } else {
      agregarTitulo(resultado.analisis ? 'Comparación de leyes' : 'Resumen de leyes de cooperativas')
      resultado.resultados.forEach((item) => {
        agregarSubtitulo(item.pais)
        if (item.comparacion) {
          item.comparacion.diferencias.forEach((d) => agregarParrafo(d.tema, d.detalle))
        } else if (item.resumen) {
          Object.entries(item.resumen).forEach(([campo, valor]) => agregarParrafo(campo.replaceAll('_', ' '), valor))
        }
        y += 6
      })
    }

    doc.save('leyai-resultado.pdf')
  }

  return (
    <div className="min-h-screen bg-[#efede6] text-[#20242b]">
      <header className="border-b border-[#20242b]/15 px-6 py-5 sm:px-10 flex items-center justify-between">
        <span className="text-lg tracking-tight text-[#24406b] font-semibold">LeyAI</span>
        <nav className="flex gap-2">
          <button onClick={() => setVista('comparar')} className={`px-3 py-1.5 rounded-sm text-sm ${vista === 'comparar' ? 'bg-[#24406b] text-white' : 'text-[#20242b]/70'}`}>
            Comparar
          </button>
          <button onClick={() => setVista('agregar')} className={`px-3 py-1.5 rounded-sm text-sm ${vista === 'agregar' ? 'bg-[#24406b] text-white' : 'text-[#20242b]/70'}`}>
            Agregar país
          </button>
        </nav>
      </header>

      {vista === 'comparar' && (
        <main className="mx-auto max-w-xl px-6 py-12 sm:px-10">
          <h1 className="font-serif-display text-3xl sm:text-4xl leading-tight">Compara leyes de cooperativas</h1>
          <p className="mt-3 text-[#20242b]/70 leading-relaxed">
            Elige hasta 3 países. Si subes un documento, se compara contra cada uno. Si no subes nada, puedes ver un resumen de cada país, o compararlos entre sí.
          </p>

          <div className="mt-8">
            <p className="text-sm text-[#20242b]/50 mb-2">Países ({paisesSeleccionados.length}/3)</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(paisesDisponibles).map(([codigo, nombre]) => {
                const seleccionado = paisesSeleccionados.includes(codigo)
                const deshabilitado = !seleccionado && paisesSeleccionados.length >= 3
                return (
                  <button
                    key={codigo}
                    type="button"
                    disabled={deshabilitado}
                    onClick={() => alternarPais(codigo)}
                    className={`px-3 py-1.5 rounded-sm text-sm border transition-colors ${
                      seleccionado ? 'bg-[#24406b] text-white border-[#24406b]' : 'bg-white/40 border-[#20242b]/25 text-[#20242b]/80 disabled:opacity-30'
                    }`}
                  >
                    {nombre}
                  </button>
                )
              })}
            </div>
          </div>

          <div onDragOver={(e) => e.preventDefault()} onDrop={manejarDrop} className="mt-6 rounded-sm border border-dashed border-[#20242b]/30 bg-white/40 px-6 py-8 text-center">
            <input id="archivo-input" type="file" accept=".pdf,.docx" onChange={manejarArchivo} className="hidden" />
            <label htmlFor="archivo-input" className="cursor-pointer">
              <p className="text-[#20242b]/80">{archivo ? archivo.name : 'Opcional, arrastra una ley para comparar, o deja vacío'}</p>
              <p className="mt-1 text-sm text-[#20242b]/50">PDF o DOCX</p>
            </label>
            {archivo && (
              <button type="button" onClick={() => setArchivo(null)} className="mt-2 text-sm text-[#7a2e27] underline">
                Quitar archivo
              </button>
            )}
          </div>

          {!archivo && paisesSeleccionados.length >= 2 && (
            <label className="mt-4 flex items-center gap-2 text-sm text-[#20242b]/80">
              <input type="checkbox" checked={compararEntreSi} onChange={(e) => setCompararEntreSi(e.target.checked)} />
              Comparar estos países entre sí (en vez de un resumen por separado)
            </label>
          )}

          <button
            onClick={comparar}
            disabled={paisesSeleccionados.length === 0 || estado === 'cargando'}
            className="mt-6 w-full rounded-sm bg-[#7a2e27] px-6 py-3 text-white font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#661f19] transition-colors"
          >
            {estado === 'cargando' ? 'Procesando…' : archivo ? 'Comparar' : compararEntreSi ? 'Comparar países' : 'Ver resumen'}
          </button>

          {estado === 'cargando' && <p className="mt-4 text-sm text-[#20242b]/60">Puede tardar uno o varios minutos, se procesan uno por uno.</p>}
          {estado === 'error' && <p className="mt-4 text-sm text-[#7a2e27]">{error}</p>}

          {estado === 'listo' && resultado && (
            <div className="mt-10 border-t border-[#20242b]/15 pt-8 space-y-8">
              <button onClick={descargarPDF} className="text-sm text-[#24406b] underline">
                Descargar como PDF
              </button>

              {resultado.analisis && (
                <div>
                  <p className="text-sm text-[#20242b]/50">Tu documento</p>
                  <p className="text-lg">{resultado.analisis.pais} — {resultado.analisis.tema}</p>
                </div>
              )}

              {resultado.comparacion_grupal ? (
                <div>
                  <p className="font-serif-display text-xl mb-3">
                    {resultado.comparacion_grupal.paises.join(' vs ')}
                  </p>
                  <ul className="space-y-3">
                    {resultado.comparacion_grupal.diferencias.map((d, j) => (
                      <li key={j}>
                        <p className="font-medium">{d.tema}</p>
                        <p className="text-[#20242b]/80 leading-relaxed">{d.detalle}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                resultado.resultados.map((item, i) => (
                  <div key={i}>
                    <p className="font-serif-display text-xl mb-3">{item.pais}</p>
                    {item.comparacion && (
                      <ul className="space-y-3">
                        {item.comparacion.diferencias.map((d, j) => (
                          <li key={j}>
                            <p className="font-medium">{d.tema}</p>
                            <p className="text-[#20242b]/80 leading-relaxed">{d.detalle}</p>
                          </li>
                        ))}
                      </ul>
                    )}
                    {item.resumen && (
                      <dl className="space-y-3">
                        {Object.entries(item.resumen).map(([campo, valor]) => (
                          <div key={campo}>
                            <dt className="text-sm text-[#20242b]/50">{campo.replaceAll('_', ' ')}</dt>
                            <dd className="text-[#20242b]/90 leading-relaxed">{valor}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </main>
      )}

      {vista === 'agregar' && (
        <main className="mx-auto max-w-xl px-6 py-12 sm:px-10">
          <h1 className="font-serif-display text-3xl sm:text-4xl leading-tight">Agregar país</h1>
          <p className="mt-3 text-[#20242b]/70 leading-relaxed">Pega el link a la ley de cooperativas de un país, o sube el PDF directamente.</p>

          <div className="mt-8">
            <label className="text-sm text-[#20242b]/50">Nombre del país</label>
            <input
              type="text"
              value={nombrePais}
              onChange={(e) => setNombrePais(e.target.value)}
              placeholder="Ej. México"
              className="mt-1 w-full rounded-sm border border-[#20242b]/25 bg-white/60 px-3 py-2 text-[#20242b] outline-none focus:border-[#24406b]"
            />
          </div>

          <div className="mt-6 flex gap-2">
            <button type="button" onClick={() => setTipoFuente('url')} className={`px-3 py-1.5 rounded-sm text-sm border ${tipoFuente === 'url' ? 'bg-[#24406b] text-white border-[#24406b]' : 'border-[#20242b]/25 text-[#20242b]/80'}`}>
              Pegar link
            </button>
            <button type="button" onClick={() => setTipoFuente('archivo')} className={`px-3 py-1.5 rounded-sm text-sm border ${tipoFuente === 'archivo' ? 'bg-[#24406b] text-white border-[#24406b]' : 'border-[#20242b]/25 text-[#20242b]/80'}`}>
              Subir PDF
            </button>
          </div>

          {tipoFuente === 'url' ? (
            <input
              type="text"
              value={urlFuente}
              onChange={(e) => setUrlFuente(e.target.value)}
              placeholder="https://..."
              className="mt-4 w-full rounded-sm border border-[#20242b]/25 bg-white/60 px-3 py-2 text-[#20242b] outline-none focus:border-[#24406b]"
            />
          ) : (
            <div className="mt-4 rounded-sm border border-dashed border-[#20242b]/30 bg-white/40 px-6 py-8 text-center">
              <input id="archivo-fuente-input" type="file" accept=".pdf,.docx" onChange={(e) => setArchivoFuente(e.target.files[0] || null)} className="hidden" />
              <label htmlFor="archivo-fuente-input" className="cursor-pointer">
                <p className="text-[#20242b]/80">{archivoFuente ? archivoFuente.name : 'Haz clic para elegir el PDF'}</p>
              </label>
            </div>
          )}

          <button
            onClick={agregarFuente}
            disabled={estadoAgregar === 'cargando'}
            className="mt-6 w-full rounded-sm bg-[#7a2e27] px-6 py-3 text-white font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#661f19] transition-colors"
          >
            {estadoAgregar === 'cargando' ? 'Agregando…' : 'Agregar país'}
          </button>

          {estadoAgregar === 'error' && <p className="mt-4 text-sm text-[#7a2e27]">{errorAgregar}</p>}
          {estadoAgregar === 'listo' && <p className="mt-4 text-sm text-[#20242b]/70">País agregado. Ya aparece en la pantalla de Comparar.</p>}

          <div className="mt-12 border-t border-[#20242b]/15 pt-8">
            <p className="text-sm text-[#20242b]/50 mb-3">Países ya cargados</p>
            <ul className="space-y-2">
              {Object.entries(paisesDisponibles).map(([codigo, nombre]) => (
                <li key={codigo} className="flex items-center justify-between">
                  <span className="text-[#20242b]/90">{nombre}</span>
                  <button type="button" onClick={() => eliminarFuente(codigo, nombre)} className="text-sm text-[#7a2e27] underline">
                    Eliminar
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </main>
      )}
    </div>
  )
}

export default App