import { useState, useEffect, useRef, useCallback } from 'react'
import jsPDF from 'jspdf'

const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

// ---------------------------------------------------------------------------
// Identificador del navegador. No es una cuenta, es una llave larga que
// permite recuperar las conversaciones sin tener que registrarse.
// ---------------------------------------------------------------------------

const CLAVE_USUARIO = 'leyai_usuario'

function obtenerUsuario() {
  try {
    let id = localStorage.getItem(CLAVE_USUARIO)
    if (!id) {
      id = (crypto.randomUUID?.() || `u${Date.now()}${Math.random()}`).replace(/[^A-Za-z0-9]/g, '')
      localStorage.setItem(CLAVE_USUARIO, id)
    }
    return id
  } catch {
    // Modo incógnito o almacenamiento bloqueado, la sesión no se guarda.
    return `temporal${Date.now()}`
  }
}

// ---------------------------------------------------------------------------
// Render de texto con formato simple (negritas, listas, títulos)
// ---------------------------------------------------------------------------

function conNegritas(texto) {
  return texto.split(/(\*\*[^*]+\*\*)/g).map((parte, i) =>
    parte.startsWith('**') && parte.endsWith('**')
      ? <strong key={i}>{parte.slice(2, -2)}</strong>
      : <span key={i}>{parte}</span>
  )
}

function TextoFormateado({ texto }) {
  const bloques = []
  let lista = null

  const cerrarLista = () => {
    if (lista) {
      bloques.push(
        lista.ordenada
          ? <ol key={bloques.length} className="list-decimal pl-5 space-y-1 my-2">{lista.items}</ol>
          : <ul key={bloques.length} className="list-disc pl-5 space-y-1 my-2">{lista.items}</ul>
      )
      lista = null
    }
  }

  texto.split('\n').forEach((linea, i) => {
    const limpia = linea.trim()

    if (!limpia) { cerrarLista(); return }

    const vinieta = limpia.match(/^[-*•]\s+(.*)$/)
    const numerada = limpia.match(/^(\d+)[.)]\s+(.*)$/)
    const titulo = limpia.match(/^#{1,4}\s+(.*)$/)

    if (titulo) {
      cerrarLista()
      bloques.push(<p key={i} className="font-semibold mt-4 mb-1">{conNegritas(titulo[1])}</p>)
      return
    }
    if (vinieta) {
      if (!lista || lista.ordenada) { cerrarLista(); lista = { ordenada: false, items: [] } }
      lista.items.push(<li key={i}>{conNegritas(vinieta[1])}</li>)
      return
    }
    if (numerada) {
      if (!lista || !lista.ordenada) { cerrarLista(); lista = { ordenada: true, items: [] } }
      lista.items.push(<li key={i}>{conNegritas(numerada[2])}</li>)
      return
    }

    cerrarLista()
    bloques.push(<p key={i} className="my-2 leading-relaxed">{conNegritas(limpia)}</p>)
  })

  cerrarLista()
  return <div>{bloques}</div>
}

// ---------------------------------------------------------------------------
// PDF
// ---------------------------------------------------------------------------

function crearPDF() {
  const doc = new jsPDF()
  const margen = 15
  const ancho = 180
  let y = 20

  const salto = (alto = 0) => {
    if (y + alto > 275) { doc.addPage(); y = 20 }
  }
  const titulo = (texto, tamano = 16) => {
    salto(12)
    doc.setFontSize(tamano); doc.setFont(undefined, 'bold')
    doc.splitTextToSize(texto, ancho).forEach((l) => { salto(8); doc.text(l, margen, y); y += 8 })
    y += 2
  }
  const parrafo = (texto) => {
    doc.setFontSize(11); doc.setFont(undefined, 'normal')
    doc.splitTextToSize(texto, ancho).forEach((l) => { salto(6); doc.text(l, margen, y); y += 6 })
    y += 3
  }
  const etiquetado = (etiqueta, texto) => {
    salto(10)
    doc.setFontSize(11); doc.setFont(undefined, 'bold')
    doc.text(etiqueta, margen, y); y += 6
    parrafo(texto)
  }

  return { doc, titulo, parrafo, etiquetado, guardar: (n) => doc.save(n) }
}

function descargarRespuesta(mensaje, pregunta) {
  const pdf = crearPDF()
  pdf.titulo('LeyAI')
  pdf.doc.setFontSize(11); pdf.doc.setFont(undefined, 'italic')
  pdf.parrafo(`Consulta: ${pregunta || ''}`)
  pdf.parrafo(mensaje.contenido.replace(/\*\*/g, ''))
  if (mensaje.fuentes?.length) {
    pdf.titulo('Fuentes consultadas', 13)
    const vistas = new Set()
    mensaje.fuentes.forEach((f) => {
      const linea = `${f.pais}${f.etiqueta ? `, ${f.etiqueta}` : ''}`
      if (!vistas.has(linea)) { vistas.add(linea); pdf.parrafo(`• ${linea}`) }
    })
  }
  pdf.guardar('leyai-respuesta.pdf')
}

// ---------------------------------------------------------------------------
// Selector de países reutilizable
// ---------------------------------------------------------------------------

function SelectorPaises({ paises, seleccionados, alternar, seleccionarTodos, limpiar, compacto }) {
  const total = Object.keys(paises).length
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm text-[#20242b]/50">
          {seleccionados.length === 0
            ? compacto ? 'Todos los países' : `Países (0/${total})`
            : `${seleccionados.length} de ${total} países`}
        </p>
        <div className="flex gap-3 text-sm">
          {seleccionados.length < total && (
            <button type="button" onClick={seleccionarTodos} className="text-[#24406b] underline">Todos</button>
          )}
          {seleccionados.length > 0 && (
            <button type="button" onClick={limpiar} className="text-[#24406b] underline">Limpiar</button>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {Object.entries(paises).map(([codigo, nombre]) => {
          const activo = seleccionados.includes(codigo)
          return (
            <button
              key={codigo}
              type="button"
              onClick={() => alternar(codigo)}
              className={`px-3 py-1.5 rounded-sm text-sm border transition-colors ${
                activo
                  ? 'bg-[#24406b] text-white border-[#24406b]'
                  : 'bg-white/40 border-[#20242b]/25 text-[#20242b]/80 hover:border-[#24406b]/50'
              }`}
            >
              {nombre}
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

const SUGERENCIAS = [
  '¿Cuántos socios se necesitan como mínimo para formar una cooperativa en cada país?',
  'Compara cómo se reparten los excedentes en Chile, España y Alemania',
  '¿Qué países exigen una reserva legal obligatoria y de cuánto?',
  'Resume el régimen de disolución y liquidación en Uruguay',
]

function Chat({ paises, usuario }) {
  const [conversaciones, setConversaciones] = useState([])
  const [conversacionId, setConversacionId] = useState(null)
  const [mensajes, setMensajes] = useState([])
  const [entrada, setEntrada] = useState('')
  const [filtro, setFiltro] = useState([])
  const [mostrarFiltro, setMostrarFiltro] = useState(false)
  const [mostrarLista, setMostrarLista] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState('')

  const finRef = useRef(null)
  const cajaRef = useRef(null)

  const cargarConversaciones = useCallback(() => {
    fetch(`${API_URL}/conversaciones/${usuario}`)
      .then((r) => (r.ok ? r.json() : []))
      .then(setConversaciones)
      .catch(() => {})
  }, [usuario])

  useEffect(() => { cargarConversaciones() }, [cargarConversaciones])

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [mensajes])

  const abrir = async (id) => {
    setMostrarLista(false)
    setError('')
    try {
      const r = await fetch(`${API_URL}/conversaciones/${usuario}/${id}`)
      if (!r.ok) throw new Error('No se pudo abrir la conversación.')
      const datos = await r.json()
      setConversacionId(datos.id)
      setMensajes(datos.mensajes || [])
    } catch (e) {
      setError(e.message)
    }
  }

  const nueva = () => {
    setConversacionId(null)
    setMensajes([])
    setError('')
    setMostrarLista(false)
  }

  const borrar = async (id, titulo) => {
    if (!window.confirm(`¿Eliminar "${titulo}"?`)) return
    await fetch(`${API_URL}/conversaciones/${usuario}/${id}`, { method: 'DELETE' }).catch(() => {})
    if (id === conversacionId) nueva()
    cargarConversaciones()
  }

  const enviar = async (textoManual) => {
    const texto = (textoManual ?? entrada).trim()
    if (!texto || enviando) return

    setEntrada('')
    setError('')
    setEnviando(true)
    setMensajes((m) => [
      ...m,
      { rol: 'usuario', contenido: texto },
      { rol: 'asistente', contenido: '', fuentes: [], pensando: true },
    ])

    try {
      const respuesta = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          usuario,
          mensaje: texto,
          conversacion_id: conversacionId,
          paises: filtro,
        }),
      })

      if (!respuesta.ok) {
        const detalle = await respuesta.json().catch(() => null)
        throw new Error(detalle?.detail || 'No se pudo enviar el mensaje.')
      }

      const lector = respuesta.body.getReader()
      const decodificador = new TextDecoder()
      let pendiente = ''

      const aplicar = (evento) => {
        if (evento.tipo === 'inicio') {
          setConversacionId(evento.conversacion_id)
          setMensajes((m) => {
            const copia = [...m]
            copia[copia.length - 1] = { ...copia[copia.length - 1], fuentes: evento.fuentes || [] }
            return copia
          })
        } else if (evento.tipo === 'delta') {
          setMensajes((m) => {
            const copia = [...m]
            const ultimo = copia[copia.length - 1]
            copia[copia.length - 1] = {
              ...ultimo,
              contenido: ultimo.contenido + evento.texto,
              pensando: false,
            }
            return copia
          })
        } else if (evento.tipo === 'fin') {
          cargarConversaciones()
        } else if (evento.tipo === 'error') {
          setError(evento.detalle)
          setMensajes((m) => m.filter((x, i) => !(i === m.length - 1 && !x.contenido)))
        }
      }

      while (true) {
        const { done, value } = await lector.read()
        if (done) break
        pendiente += decodificador.decode(value, { stream: true })
        const partes = pendiente.split('\n\n')
        pendiente = partes.pop() || ''
        for (const parte of partes) {
          const linea = parte.trim()
          if (!linea.startsWith('data:')) continue
          try {
            aplicar(JSON.parse(linea.slice(5).trim()))
          } catch {
            // fragmento incompleto, se ignora
          }
        }
      }
    } catch (e) {
      setError(e.message)
      setMensajes((m) => m.filter((x, i) => !(i === m.length - 1 && !x.contenido)))
    } finally {
      setEnviando(false)
      setMensajes((m) => m.map((x) => ({ ...x, pensando: false })))
    }
  }

  const alTeclear = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      enviar()
    }
  }

  const ajustarAlto = (e) => {
    setEntrada(e.target.value)
    const caja = cajaRef.current
    if (caja) {
      caja.style.height = 'auto'
      caja.style.height = `${Math.min(caja.scrollHeight, 180)}px`
    }
  }

  const ultimaPregunta = (indice) => {
    for (let i = indice - 1; i >= 0; i--) {
      if (mensajes[i].rol === 'usuario') return mensajes[i].contenido
    }
    return ''
  }

  return (
    <div className="mx-auto max-w-5xl px-4 sm:px-8 py-6 flex gap-6">
      {/* Lista de conversaciones */}
      <aside
        className={`${mostrarLista ? 'block' : 'hidden'} md:block fixed md:static inset-0 z-20 md:z-auto bg-[#efede6] md:bg-transparent p-4 md:p-0 md:w-56 shrink-0`}
      >
        <div className="flex items-center justify-between md:block">
          <button
            onClick={nueva}
            className="w-full md:w-auto md:mb-4 rounded-sm border border-[#24406b] px-3 py-1.5 text-sm text-[#24406b] hover:bg-[#24406b] hover:text-white transition-colors"
          >
            Nueva conversación
          </button>
          <button onClick={() => setMostrarLista(false)} className="md:hidden ml-3 text-sm text-[#20242b]/60">
            Cerrar
          </button>
        </div>

        <ul className="mt-4 md:mt-0 space-y-1 overflow-y-auto max-h-[70vh]">
          {conversaciones.map((c) => (
            <li key={c.id} className="group flex items-center gap-1">
              <button
                onClick={() => abrir(c.id)}
                className={`flex-1 text-left text-sm px-2 py-1.5 rounded-sm truncate ${
                  c.id === conversacionId ? 'bg-[#24406b]/10 text-[#24406b]' : 'text-[#20242b]/70 hover:bg-white/50'
                }`}
                title={c.titulo}
              >
                {c.titulo}
              </button>
              <button
                onClick={() => borrar(c.id, c.titulo)}
                className="opacity-0 group-hover:opacity-100 text-xs text-[#7a2e27] px-1"
                aria-label="Eliminar"
              >
                ✕
              </button>
            </li>
          ))}
          {conversaciones.length === 0 && (
            <li className="text-sm text-[#20242b]/40 px-2">Todavía no hay conversaciones.</li>
          )}
        </ul>
      </aside>

      {/* Conversación */}
      <div className="flex-1 min-w-0 flex flex-col" style={{ minHeight: 'calc(100vh - 140px)' }}>
        <button
          onClick={() => setMostrarLista(true)}
          className="md:hidden self-start mb-3 text-sm text-[#24406b] underline"
        >
          Ver conversaciones
        </button>

        {mensajes.length === 0 ? (
          <div className="flex-1 flex flex-col justify-center py-8">
            <h1 className="font-serif-display text-3xl sm:text-4xl leading-tight">
              Pregúntale a LeyAI
            </h1>
            <p className="mt-3 text-[#20242b]/70 leading-relaxed">
              Escribe lo que quieras saber sobre las leyes de cooperativas cargadas. Puedes pedir
              resúmenes, comparaciones entre los países que quieras, o preguntar por un artículo
              específico.
            </p>
            <div className="mt-6 space-y-2">
              {SUGERENCIAS.map((s) => (
                <button
                  key={s}
                  onClick={() => enviar(s)}
                  className="block w-full text-left text-sm rounded-sm border border-[#20242b]/20 bg-white/40 px-3 py-2 text-[#20242b]/80 hover:border-[#24406b]/50 transition-colors"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex-1 space-y-6 pb-4">
            {mensajes.map((m, i) =>
              m.rol === 'usuario' ? (
                <div key={i} className="flex justify-end">
                  <div className="max-w-[85%] rounded-sm bg-[#24406b] px-4 py-2.5 text-white whitespace-pre-wrap">
                    {m.contenido}
                  </div>
                </div>
              ) : (
                <div key={i} className="max-w-[95%]">
                  {m.pensando && !m.contenido ? (
                    <p className="text-[#20242b]/50 text-sm">Buscando en las leyes…</p>
                  ) : (
                    <>
                      <div className="text-[#20242b]/90">
                        <TextoFormateado texto={m.contenido} />
                      </div>
                      {m.fuentes?.length > 0 && (
                        <details className="mt-3 text-sm">
                          <summary className="cursor-pointer text-[#20242b]/50">
                            Fuentes consultadas ({new Set(m.fuentes.map((f) => f.pais)).size} países)
                          </summary>
                          <ul className="mt-2 space-y-1 text-[#20242b]/70">
                            {m.fuentes.map((f, j) => (
                              <li key={j}>
                                {f.pais}
                                {f.etiqueta ? `, ${f.etiqueta}` : ''}
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                      {!enviando && m.contenido && (
                        <button
                          onClick={() => descargarRespuesta(m, ultimaPregunta(i))}
                          className="mt-2 text-sm text-[#24406b] underline"
                        >
                          Descargar como PDF
                        </button>
                      )}
                    </>
                  )}
                </div>
              )
            )}
            <div ref={finRef} />
          </div>
        )}

        {error && <p className="text-sm text-[#7a2e27] mb-2">{error}</p>}

        {/* Caja de escritura */}
        <div className="sticky bottom-0 bg-[#efede6] pt-2 pb-4">
          {mostrarFiltro && (
            <div className="mb-3 rounded-sm border border-[#20242b]/20 bg-white/50 p-3">
              <SelectorPaises
                paises={paises}
                seleccionados={filtro}
                compacto
                alternar={(c) =>
                  setFiltro((a) => (a.includes(c) ? a.filter((x) => x !== c) : [...a, c]))
                }
                seleccionarTodos={() => setFiltro(Object.keys(paises))}
                limpiar={() => setFiltro([])}
              />
            </div>
          )}

          <div className="flex items-end gap-2">
            <button
              onClick={() => setMostrarFiltro((v) => !v)}
              className={`shrink-0 rounded-sm border px-3 py-2.5 text-sm transition-colors ${
                filtro.length > 0
                  ? 'border-[#24406b] bg-[#24406b] text-white'
                  : 'border-[#20242b]/25 text-[#20242b]/70'
              }`}
              title="Limitar la búsqueda a ciertos países"
            >
              {filtro.length > 0 ? `${filtro.length} países` : 'Todos'}
            </button>
            <textarea
              ref={cajaRef}
              rows={1}
              value={entrada}
              onChange={ajustarAlto}
              onKeyDown={alTeclear}
              placeholder="Escribe tu pregunta…"
              className="flex-1 resize-none rounded-sm border border-[#20242b]/25 bg-white/70 px-3 py-2.5 outline-none focus:border-[#24406b]"
            />
            <button
              onClick={() => enviar()}
              disabled={enviando || !entrada.trim()}
              className="shrink-0 rounded-sm bg-[#7a2e27] px-5 py-2.5 text-white font-medium disabled:opacity-40 hover:bg-[#661f19] transition-colors"
            >
              {enviando ? '…' : 'Enviar'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Comparar
// ---------------------------------------------------------------------------

function Comparar({ paises }) {
  const [seleccionados, setSeleccionados] = useState([])
  const [archivo, setArchivo] = useState(null)
  const [compararEntreSi, setCompararEntreSi] = useState(false)
  const [estado, setEstado] = useState('inicial')
  const [resultado, setResultado] = useState(null)
  const [error, setError] = useState('')

  const limpiarResultado = () => { setEstado('inicial'); setResultado(null); setError('') }

  const manejarDrop = (e) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) { setArchivo(file); limpiarResultado() }
  }

  const comparar = async () => {
    if (seleccionados.length === 0) return
    setEstado('cargando'); setError('')

    const formData = new FormData()
    seleccionados.forEach((p) => formData.append('paises', p))
    if (archivo) formData.append('archivo', archivo)
    if (!archivo && compararEntreSi && seleccionados.length >= 2) {
      formData.append('comparar_entre_si', 'true')
    }

    try {
      const respuesta = await fetch(`${API_URL}/comparar`, { method: 'POST', body: formData })
      if (!respuesta.ok) {
        const detalle = await respuesta.json().catch(() => null)
        throw new Error(detalle?.detail || 'Ocurrió un error al procesar la solicitud.')
      }
      setResultado(await respuesta.json())
      setEstado('listo')
    } catch (err) {
      setError(err.message); setEstado('error')
    }
  }

  const descargarPDF = () => {
    if (!resultado) return
    const pdf = crearPDF()

    if (resultado.comparacion_grupal) {
      pdf.titulo(`Diferencias entre ${resultado.comparacion_grupal.paises.join(', ')}`)
      resultado.comparacion_grupal.diferencias.forEach((d) => pdf.etiquetado(d.tema, d.detalle))
    } else {
      pdf.titulo(resultado.analisis ? 'Comparación de leyes' : 'Resumen de leyes de cooperativas')
      resultado.resultados.forEach((item) => {
        pdf.titulo(item.pais, 13)
        if (item.comparacion) {
          item.comparacion.diferencias.forEach((d) => pdf.etiquetado(d.tema, d.detalle))
        } else if (item.resumen) {
          Object.entries(item.resumen).forEach(([campo, valor]) =>
            pdf.etiquetado(campo.replaceAll('_', ' '), String(valor))
          )
        }
      })
    }
    pdf.guardar('leyai-resultado.pdf')
  }

  return (
    <main className="mx-auto max-w-xl px-6 py-12 sm:px-10">
      <h1 className="font-serif-display text-3xl sm:text-4xl leading-tight">Compara leyes de cooperativas</h1>
      <p className="mt-3 text-[#20242b]/70 leading-relaxed">
        Elige los países que quieras. Si subes un documento, se compara contra cada uno. Si no subes
        nada, puedes ver un resumen de cada país, o compararlos entre sí.
      </p>

      <div className="mt-8">
        <SelectorPaises
          paises={paises}
          seleccionados={seleccionados}
          alternar={(c) =>
            setSeleccionados((a) => (a.includes(c) ? a.filter((x) => x !== c) : [...a, c]))
          }
          seleccionarTodos={() => setSeleccionados(Object.keys(paises))}
          limpiar={() => setSeleccionados([])}
        />
      </div>

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={manejarDrop}
        className="mt-6 rounded-sm border border-dashed border-[#20242b]/30 bg-white/40 px-6 py-8 text-center"
      >
        <input
          id="archivo-input"
          type="file"
          accept=".pdf,.docx"
          onChange={(e) => { setArchivo(e.target.files[0] || null); limpiarResultado() }}
          className="hidden"
        />
        <label htmlFor="archivo-input" className="cursor-pointer">
          <p className="text-[#20242b]/80">
            {archivo ? archivo.name : 'Opcional, arrastra una ley para comparar, o deja vacío'}
          </p>
          <p className="mt-1 text-sm text-[#20242b]/50">PDF o DOCX</p>
        </label>
        {archivo && (
          <button type="button" onClick={() => setArchivo(null)} className="mt-2 text-sm text-[#7a2e27] underline">
            Quitar archivo
          </button>
        )}
      </div>

      {!archivo && seleccionados.length >= 2 && (
        <label className="mt-4 flex items-center gap-2 text-sm text-[#20242b]/80">
          <input
            type="checkbox"
            checked={compararEntreSi}
            onChange={(e) => setCompararEntreSi(e.target.checked)}
          />
          Comparar estos países entre sí (en vez de un resumen por separado)
        </label>
      )}

      <button
        onClick={comparar}
        disabled={seleccionados.length === 0 || estado === 'cargando'}
        className="mt-6 w-full rounded-sm bg-[#7a2e27] px-6 py-3 text-white font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-[#661f19] transition-colors"
      >
        {estado === 'cargando' ? 'Procesando…' : archivo ? 'Comparar' : compararEntreSi ? 'Comparar países' : 'Ver resumen'}
      </button>

      {estado === 'cargando' && (
        <p className="mt-4 text-sm text-[#20242b]/60">
          Puede tardar varios minutos si elegiste muchos países.
        </p>
      )}
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
                        <dd className="text-[#20242b]/90 leading-relaxed">{String(valor)}</dd>
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
  )
}

// ---------------------------------------------------------------------------
// Agregar país
// ---------------------------------------------------------------------------

function AgregarPais({ paises, recargar }) {
  const [nombrePais, setNombrePais] = useState('')
  const [tipoFuente, setTipoFuente] = useState('url')
  const [urlFuente, setUrlFuente] = useState('')
  const [archivoFuente, setArchivoFuente] = useState(null)
  const [estado, setEstado] = useState('inicial')
  const [mensaje, setMensaje] = useState('')
  const [error, setError] = useState('')

  const agregar = async () => {
    if (!nombrePais.trim()) return
    if (tipoFuente === 'url' && !urlFuente.trim()) return
    if (tipoFuente === 'archivo' && !archivoFuente) return

    setEstado('cargando'); setError('')

    const formData = new FormData()
    formData.append('nombre_pais', nombrePais.trim())
    if (tipoFuente === 'url') formData.append('url', urlFuente.trim())
    else formData.append('archivo', archivoFuente)

    try {
      const respuesta = await fetch(`${API_URL}/fuentes`, { method: 'POST', body: formData })
      if (!respuesta.ok) {
        const detalle = await respuesta.json().catch(() => null)
        throw new Error(detalle?.detail || 'No se pudo agregar la fuente.')
      }
      const datos = await respuesta.json()
      setEstado('listo')
      setMensaje(
        datos.indexado
          ? `${datos.nombre} quedó agregado e indexado. Ya puedes preguntarle en el chat.`
          : `${datos.nombre} se guardó, pero no se pudo indexar. Aparecerá en Comparar, no en el chat.`
      )
      setNombrePais(''); setUrlFuente(''); setArchivoFuente(null)
      recargar()
    } catch (err) {
      setError(err.message); setEstado('error')
    }
  }

  const eliminar = async (codigo, nombre) => {
    if (!window.confirm(`¿Eliminar ${nombre}? Esta acción no se puede deshacer.`)) return
    try {
      const respuesta = await fetch(`${API_URL}/fuentes/${codigo}`, { method: 'DELETE' })
      if (!respuesta.ok) {
        const detalle = await respuesta.json().catch(() => null)
        throw new Error(detalle?.detail || 'No se pudo eliminar el país.')
      }
      recargar()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <main className="mx-auto max-w-xl px-6 py-12 sm:px-10">
      <h1 className="font-serif-display text-3xl sm:text-4xl leading-tight">Agregar país</h1>
      <p className="mt-3 text-[#20242b]/70 leading-relaxed">
        Pega el link a la ley de cooperativas de un país, o sube el PDF directamente. Si la página
        necesita JavaScript para mostrar la ley, el link no va a funcionar, sube el PDF.
      </p>

      <div className="mt-8">
        <label className="text-sm text-[#20242b]/50">Nombre del país</label>
        <input
          type="text"
          value={nombrePais}
          onChange={(e) => setNombrePais(e.target.value)}
          placeholder="Ej. México"
          className="mt-1 w-full rounded-sm border border-[#20242b]/25 bg-white/60 px-3 py-2 outline-none focus:border-[#24406b]"
        />
      </div>

      <div className="mt-6 flex gap-2">
        {[['url', 'Pegar link'], ['archivo', 'Subir PDF']].map(([valor, texto]) => (
          <button
            key={valor}
            type="button"
            onClick={() => setTipoFuente(valor)}
            className={`px-3 py-1.5 rounded-sm text-sm border ${
              tipoFuente === valor
                ? 'bg-[#24406b] text-white border-[#24406b]'
                : 'border-[#20242b]/25 text-[#20242b]/80'
            }`}
          >
            {texto}
          </button>
        ))}
      </div>

      {tipoFuente === 'url' ? (
        <input
          type="text"
          value={urlFuente}
          onChange={(e) => setUrlFuente(e.target.value)}
          placeholder="https://..."
          className="mt-4 w-full rounded-sm border border-[#20242b]/25 bg-white/60 px-3 py-2 outline-none focus:border-[#24406b]"
        />
      ) : (
        <div className="mt-4 rounded-sm border border-dashed border-[#20242b]/30 bg-white/40 px-6 py-8 text-center">
          <input
            id="archivo-fuente-input"
            type="file"
            accept=".pdf,.docx"
            onChange={(e) => setArchivoFuente(e.target.files[0] || null)}
            className="hidden"
          />
          <label htmlFor="archivo-fuente-input" className="cursor-pointer">
            <p className="text-[#20242b]/80">{archivoFuente ? archivoFuente.name : 'Haz clic para elegir el PDF'}</p>
          </label>
        </div>
      )}

      <button
        onClick={agregar}
        disabled={estado === 'cargando'}
        className="mt-6 w-full rounded-sm bg-[#7a2e27] px-6 py-3 text-white font-medium disabled:opacity-40 hover:bg-[#661f19] transition-colors"
      >
        {estado === 'cargando' ? 'Agregando e indexando…' : 'Agregar país'}
      </button>

      {estado === 'cargando' && (
        <p className="mt-3 text-sm text-[#20242b]/60">
          Además de descargar la ley hay que indexarla, demora un poco.
        </p>
      )}
      {estado === 'error' && <p className="mt-4 text-sm text-[#7a2e27]">{error}</p>}
      {estado === 'listo' && <p className="mt-4 text-sm text-[#20242b]/70">{mensaje}</p>}

      <div className="mt-12 border-t border-[#20242b]/15 pt-8">
        <p className="text-sm text-[#20242b]/50 mb-3">Países ya cargados ({Object.keys(paises).length})</p>
        <ul className="space-y-2">
          {Object.entries(paises).map(([codigo, nombre]) => (
            <li key={codigo} className="flex items-center justify-between">
              <span className="text-[#20242b]/90">{nombre}</span>
              <button type="button" onClick={() => eliminar(codigo, nombre)} className="text-sm text-[#7a2e27] underline">
                Eliminar
              </button>
            </li>
          ))}
        </ul>
      </div>
    </main>
  )
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

function App() {
  const [vista, setVista] = useState('chat')
  const [paises, setPaises] = useState({})
  const [usuario] = useState(obtenerUsuario)

  const cargarPaises = useCallback(() => {
    fetch(`${API_URL}/paises`)
      .then((r) => r.json())
      .then(setPaises)
      .catch(() => {})
  }, [])

  useEffect(() => { cargarPaises() }, [cargarPaises])

  const pestanas = [
    ['chat', 'Chat'],
    ['comparar', 'Comparar'],
    ['agregar', 'Agregar país'],
  ]

  return (
    <div className="min-h-screen bg-[#efede6] text-[#20242b]">
      <header className="border-b border-[#20242b]/15 px-4 py-4 sm:px-10 flex items-center justify-between">
        <span className="text-lg tracking-tight text-[#24406b] font-semibold">LeyAI</span>
        <nav className="flex gap-1 sm:gap-2">
          {pestanas.map(([clave, texto]) => (
            <button
              key={clave}
              onClick={() => setVista(clave)}
              className={`px-3 py-1.5 rounded-sm text-sm ${
                vista === clave ? 'bg-[#24406b] text-white' : 'text-[#20242b]/70'
              }`}
            >
              {texto}
            </button>
          ))}
        </nav>
      </header>

      {vista === 'chat' && <Chat paises={paises} usuario={usuario} />}
      {vista === 'comparar' && <Comparar paises={paises} />}
      {vista === 'agregar' && <AgregarPais paises={paises} recargar={cargarPaises} />}
    </div>
  )
}

export default App
