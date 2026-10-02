# apps/recruitment/exports_word.py
# Llena el Descriptivo de Puesto oficial de GPA (FO-C0-CH-04, Word) con los
# datos de una version de DescriptivoPuesto -- NUNCA cambia su diseño: edita
# unicamente word/document.xml dentro del paquete .docx original, asi que
# encabezado, pie con imagenes, estilos y el glosario de textos guia quedan
# byte por byte como en la plantilla (mismo criterio que exports.py con los
# .xlsx).
#
# El formulario esta hecho de controles de contenido de Word (w:sdt): 63 en
# total (25 campos de texto, 1 fecha, 37 casillas). Se localizan por su
# posicion en el documento y CADA entrada de los mapas de abajo trae la
# etiqueta que debe tener al lado: se verifica al exportar, asi que si
# alguien cambia la plantilla y se corre un control, falla en voz alta en vez
# de escribir en el campo equivocado.
#
# Reglas de llenado (confirmadas 2026-10-02, igual que en el Excel):
# - Lo que no tiene dato se deja como la plantilla (texto guia gris incluido):
#   un campo vacio nunca se inventa.
# - Las firmas ("Nombre y Firma de conformidad") se dejan en blanco: es para
#   imprimir y firmar a mano.
# - "Funciones y responsabilidades institucionales" y la indicacion de
#   "Recursos necesarios" son texto del formato, no del puesto: no se tocan.
import io
import re
import zipfile
from xml.dom import Node, minidom

from django.utils.text import slugify

from apps.recruitment.exports import PLANTILLAS_DIR

PLANTILLA = PLANTILLAS_DIR / "FO-C0-CH-04_descriptivo_de_puesto_v6.docx"
_DOCUMENTO_XML = "word/document.xml"
_TOTAL_CONTROLES = 63


def _codigo(nombre):
    # Igual que NamedCatalog.save(): slug del nombre, truncado al largo de la
    # columna `code` (50). Sin el recorte, un nombre largo -- p. ej. el
    # recurso "Fondo fijo o caja chica asignada (...)" -- no coincidiria con
    # el code realmente guardado.
    return slugify(nombre)[:50]


_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

# -- Campos de texto: campo del modelo -> (posicion del control, texto que
# debe aparecer en SU FILA de la tabla).
_TEXTOS = {
    "nombre_puesto": (0, "Nombre del puesto"),
    "empresa": (1, "Empresa"),
    "area_departamento": (2, "Área / Departamento"),
    "reporta_a": (3, "Reporta a"),
    "supervisa_a": (4, "Supervisa a"),
    "proposito": (21, "Propósito general del puesto"),
    "decisiones_operativas": (28, "Decisiones operativas"),
    "decisiones_funcionales": (29, "Decisiones funcionales"),
    "decisiones_estrategicas": (30, "Decisiones estratégicas"),
    "relaciones_internas": (31, "Internas"),
    "relaciones_externas": (32, "Externas"),
    "escolaridad_minima": (33, "Escolaridad mínima"),
    "experiencia_requerida": (34, "Experiencia requerida"),
    "idiomas": (35, "Idiomas"),
    "competencias_tecnicas": (36, "Competencias y/o Habilidades técnicas"),
}
_FECHA = (5, "Fecha de elaboración")

# Filas numeradas: (posicion de cada control, etiqueta que lleva su fila).
_FUNCIONES = [(22, "Responsabilidad 1"), (23, "Responsabilidad 2"), (24, "Responsabilidad 3"),
              (25, "Responsabilidad 4"), (26, "Responsabilidad 5")]
_INDICADORES = [(60, "Indicador 1"), (61, "Indicador 2"), (62, "Indicador 3")]

# -- Casillas. Clave: code del catalogo (se calcula con slugify del nombre
# sembrado -- el code no cambia aunque alguien edite el nombre en el admin).
# Valor: (posicion del control, donde esta su etiqueta, etiqueta esperada).
# "parrafo": la casilla y su etiqueta comparten parrafo. "celda_previa": la
# casilla es una celda propia y su etiqueta esta en la celda de su izquierda.
_EDAD = {
    _codigo("18-25 años"): (6, "parrafo", "18- 25 años"),
    _codigo("26-35 años"): (7, "parrafo", "26- 35 años"),
    _codigo("36-45 años"): (8, "parrafo", "36-45 años"),
    _codigo("46-55 años"): (9, "parrafo", "46-55 años"),
    _codigo("Otro"): (10, "parrafo", "Otro:"),
}
_VIAJAR = {True: (11, "parrafo", "SI"), False: (12, "parrafo", "NO")}
_DIAS = {
    _codigo("Lunes a Viernes"): (13, "parrafo", "Lunes a Viernes"),
    _codigo("Lunes a Domingo"): (14, "parrafo", "Lunes a Domingo"),
    _codigo("Otro"): (15, "parrafo", "Otro:"),
}
_HORARIO = {
    _codigo("8:00 - 17:45"): (16, "parrafo", "08:00-17:45"),
    _codigo("7:00 - 16:00"): (17, "parrafo", "07:00-16:00"),
    _codigo("15:00 - 24:00"): (18, "parrafo", "15:00-24:00"),
    _codigo("23:30 - 07:30"): (19, "parrafo", "23:30-07:30"),
    _codigo("Otro"): (20, "parrafo", "Otro:"),
}
_COMPETENCIAS = {
    _codigo(nombre): (indice, "celda_previa", etiqueta)
    for indice, (nombre, etiqueta) in enumerate([
        ("Integridad", "Integridad"),
        ("Orientación a resultados", "Orientación a resultados"),
        ("Trabajo en equipo y colaboración", "Trabajo en equipo y colaboración"),
        ("Comunicación clara y efectiva", "Comunicación clara y efectiva"),
        ("Adaptabilidad y flexibilidad", "Adaptabilidad y flexibilidad"),
        ("Innovación", "Innovación"),
        ("Liderazgo", "Liderazgo"),
        ("Orientación al cliente", "Orientación al cliente"),
        ("Planificación y organización", "Planificación y organización"),
        ("Seguridad y sustentabilidad", "Seguridad y sustentabilidad"),
        ("Resolución de conflictos y toma de decisiones", "Resolución de conflictos y toma de decisiones"),
        ("Gestión del tiempo", "Gestión del tiempo"),
    ], start=37)
}
_RECURSOS = {
    _codigo(nombre): (indice, "celda_previa", etiqueta)
    for indice, (nombre, etiqueta) in zip(
        [50, 51, 52, 53, 54, 55, 56, 57, 58, 59],
        [
            ("Equipo de cómputo/laptop", "Equipo de cómputo"),
            ("Vehículo asignado", "Vehículo asignado"),
            ("Teléfono corporativo", "Teléfono corporativo"),
            ("Tarjeta de gasolina", "Tarjeta de gasolina"),
            ("Correo electrónico institucional", "Correo electrónico institucional"),
            ("Tarjeta de viáticos", "Tarjeta de viáticos"),
            ("Acceso a sistemas internos", "Acceso a sistemas internos"),
            ("Fondo fijo o caja chica asignada (para manejo de efectivo)", "Fondo fijo o caja chica"),
            ("Herramientas y/o equipos asignados", "Herramientas y/o equipos asignados"),
            ("Uniforme/EPP", "Uniforme/EPP"),
        ],
    )
}

# Renglones "Otro: ______": (control de la casilla que los acompaña, o None si
# es un renglon suelto, y el texto con el que empieza el parrafo).
_OTRO_EDAD = 10
_OTRO_DIAS = 15
_OTRO_HORARIO = 20
_OTRAS_COMPETENCIAS = "Otras:"
_OTRO_RECURSO_JUNTO_A = (59, "Otro:")


# --------------------------------------------------------------------- XML
def _hijos(nodo, etiqueta):
    return [h for h in nodo.childNodes if h.nodeType == Node.ELEMENT_NODE and h.tagName == etiqueta]


def _ancestro(nodo, etiqueta):
    actual = nodo.parentNode
    while actual is not None and getattr(actual, "tagName", None) != etiqueta:
        actual = actual.parentNode
    return actual


def _texto_de(nodo):
    return "".join(t.firstChild.data for t in nodo.getElementsByTagName("w:t") if t.firstChild)


def _elemento(documento, etiqueta, atributos=None):
    elemento = documento.createElement(etiqueta)
    for nombre, valor in (atributos or {}).items():
        elemento.setAttribute(nombre, valor)
    return elemento


def _sin_caracteres_invalidos(texto):
    # XML 1.0 no admite la mayoria de los caracteres de control.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", texto)


def _run(documento, texto, subrayado=False):
    """
    Un fragmento de texto como lo escribiria Word dentro de un control: con el
    estilo de caracter "Cuerpo" de la plantilla (Arial 10, color automatico) y
    NO con la cursiva gris del texto guia. Es de UNA sola linea: los textos de
    varias lineas se reparten en parrafos (ver _llenar_texto), porque una
    linea terminada en salto manual dentro de una celda justificada la estira
    hasta el margen en Word.
    """
    texto = re.sub(r"\s*(?:\r\n|\r|\n)\s*", " ", _sin_caracteres_invalidos(texto))
    run = _elemento(documento, "w:r")
    propiedades = _elemento(documento, "w:rPr")
    propiedades.appendChild(_elemento(documento, "w:rStyle", {"w:val": "Cuerpo"}))
    propiedades.appendChild(_elemento(documento, "w:rFonts", {"w:ascii": "Arial", "w:hAnsi": "Arial", "w:cs": "Arial"}))
    propiedades.appendChild(_elemento(documento, "w:sz", {"w:val": "20"}))
    propiedades.appendChild(_elemento(documento, "w:szCs", {"w:val": "20"}))
    if subrayado:
        propiedades.appendChild(_elemento(documento, "w:u", {"w:val": "single"}))
    run.appendChild(propiedades)
    texto_xml = _elemento(documento, "w:t", {"xml:space": "preserve"})
    texto_xml.appendChild(documento.createTextNode(texto))
    run.appendChild(texto_xml)
    return run


# ------------------------------------------------------------ verificacion
def _contexto(sdt, donde):
    if donde == "fila":
        return _texto_de(_ancestro(sdt, "w:tr"))
    if donde == "parrafo":
        return _texto_de(_ancestro(sdt, "w:p"))
    if donde == "celda_previa":
        anterior = sdt.previousSibling
        while anterior is not None and getattr(anterior, "tagName", None) != "w:tc":
            anterior = anterior.previousSibling
        return _texto_de(anterior) if anterior is not None else ""
    raise ValueError(donde)


def _verificar(controles, indice, donde, esperado):
    """Aborta si el control en `indice` no esta junto a su etiqueta: la plantilla cambio."""
    contexto = _contexto(controles[indice], donde)
    if esperado not in contexto:
        raise RuntimeError(
            f"La plantilla del Descriptivo cambió: el control {indice} debería estar junto a "
            f"'{esperado}' pero junto a él dice '{contexto[:80]}'. Revisa exports_word.py."
        )
    return controles[indice]


# ---------------------------------------------------------------- llenado
def _quitar_marcador(sdt):
    propiedades = _hijos(sdt, "w:sdtPr")[0]
    for marcador in _hijos(propiedades, "w:showingPlcHdr"):
        propiedades.removeChild(marcador)
    return propiedades


def _llenar_texto(documento, sdt, valor):
    """Reemplaza el texto guia de un control de texto por `valor`."""
    _quitar_marcador(sdt)
    primer_parrafo = _hijos(sdt, "w:sdtContent")[0].getElementsByTagName("w:p")[0]
    contenedor = primer_parrafo.parentNode
    for parrafo in _hijos(contenedor, "w:p"):
        if parrafo is not primer_parrafo:
            contenedor.removeChild(parrafo)
    for hijo in list(primer_parrafo.childNodes):
        if getattr(hijo, "tagName", None) != "w:pPr":
            primer_parrafo.removeChild(hijo)
    # La marca de parrafo de la plantilla hereda negrita/cursiva/gris del
    # texto guia: se limpia para que lo que se siga escribiendo en Word no
    # salga con ese formato.
    for propiedades in primer_parrafo.getElementsByTagName("w:pPr"):
        for rpr in _hijos(propiedades, "w:rPr"):
            for etiqueta in ("w:b", "w:bCs", "w:i", "w:iCs", "w:color"):
                for sobrante in _hijos(rpr, etiqueta):
                    rpr.removeChild(sobrante)
    # Un parrafo por linea, todos con el formato del parrafo de la plantilla
    # (justificado): asi la ultima linea de cada uno no se estira.
    lineas = re.split(r"\r\n|\r|\n", valor)
    primer_parrafo.appendChild(_run(documento, lineas[0]))
    anterior = primer_parrafo
    for linea in lineas[1:]:
        parrafo = _elemento(documento, "w:p")
        for propiedades in _hijos(primer_parrafo, "w:pPr"):
            parrafo.appendChild(propiedades.cloneNode(True))
        parrafo.appendChild(_run(documento, linea))
        contenedor.insertBefore(parrafo, anterior.nextSibling)
        anterior = parrafo


def _llenar_fecha(documento, sdt, fecha):
    propiedades = _quitar_marcador(sdt)
    propiedades.getElementsByTagName("w:date")[0].setAttribute("w:fullDate", f"{fecha:%Y-%m-%d}T00:00:00Z")
    _llenar_texto(documento, sdt, f"{fecha.day} de {_MESES[fecha.month - 1]} de {fecha.year}")


def _marcar(sdt):
    """Marca una casilla igual que Word: w14:checked=1, simbolo ☒ y la fuente de ese estado."""
    sdt.getElementsByTagName("w14:checked")[0].setAttribute("w14:val", "1")
    run = _hijos(sdt, "w:sdtContent")[0].getElementsByTagName("w:r")[0]
    run.getElementsByTagName("w:t")[0].firstChild.data = "☒"
    fuentes = run.getElementsByTagName("w:rFonts")[0]
    for atributo in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        fuentes.setAttribute(atributo, "MS Gothic")
    if fuentes.hasAttribute("w:cs"):
        fuentes.removeAttribute("w:cs")
    fuentes.setAttribute("w:hint", "eastAsia")


def _escribir_en_renglon_otro(documento, parrafo, prefijo, valor):
    """
    Cambia la linea de guiones bajos de un renglon "Otro: ______" por `valor`
    (subrayado, para conservar el aspecto de renglon llenado a mano). Los
    guiones bajos son texto simple repartido en varios fragmentos, no un
    control de Word.
    """
    if prefijo not in _texto_de(parrafo):
        raise RuntimeError(f"La plantilla del Descriptivo cambió: se esperaba un renglón '{prefijo}'.")
    fragmentos = [r for r in _hijos(parrafo, "w:r") if "_" in _texto_de(r)]
    if not fragmentos:
        raise RuntimeError(f"La plantilla del Descriptivo cambió: el renglón '{prefijo}' ya no trae su línea.")
    primero = fragmentos[0]
    etiqueta = _texto_de(primero).split("_")[0]
    texto_etiqueta = primero.getElementsByTagName("w:t")[0]
    texto_etiqueta.firstChild.data = etiqueta
    texto_etiqueta.setAttribute("xml:space", "preserve")
    for sobrante in fragmentos[1:]:
        parrafo.removeChild(sobrante)
    parrafo.insertBefore(_run(documento, valor, subrayado=True), primero.nextSibling)


def _parrafo_suelto(documento, prefijo):
    """El unico parrafo del documento que empieza con `prefijo` y trae una linea de guiones bajos."""
    encontrados = [
        p for p in documento.getElementsByTagName("w:p")
        if _texto_de(p).startswith(prefijo) and "_" in _texto_de(p)
    ]
    if len(encontrados) != 1:
        raise RuntimeError(
            f"La plantilla del Descriptivo cambió: se esperaba exactamente un renglón '{prefijo}' "
            f"y hay {len(encontrados)}."
        )
    return encontrados[0]


def _quitar_ids_de_parrafo(nodo):
    for elemento in [nodo] + list(nodo.getElementsByTagName("*")):
        for atributo in ("w14:paraId", "w14:textId"):
            if elemento.hasAttribute(atributo):
                elemento.removeAttribute(atributo)


def _agregar_filas(documento, controles, filas_del_formulario, textos, prefijo_etiqueta):
    """
    Si hay mas funciones/indicadores que filas trae el formulario (5 y 3), se
    clona la ultima fila -- como lo haria una persona en Word -- numerada con
    el siguiente numero. Se clona ANTES de llenar la fila modelo, para que la
    copia salga con el texto guia limpio.
    """
    indice_ultimo, _ = filas_del_formulario[-1]
    fila_modelo = _ancestro(controles[indice_ultimo], "w:tr")
    ids_usados = {
        elemento.getAttribute("w:val")
        for elemento in documento.getElementsByTagName("w:id")
        if elemento.parentNode.tagName == "w:sdtPr"
    }
    siguiente_id = max(int(i) for i in ids_usados) + 1
    anterior = fila_modelo
    nuevos = []
    for numero in range(len(filas_del_formulario) + 1, len(textos) + 1):
        fila = fila_modelo.cloneNode(True)
        _quitar_ids_de_parrafo(fila)
        etiquetas = _hijos(fila, "w:tc")[0].getElementsByTagName("w:t")
        etiquetas[0].firstChild.data = f"{prefijo_etiqueta} {numero}"
        for sobrante in etiquetas[1:]:
            sobrante.parentNode.removeChild(sobrante)
        sdt = fila.getElementsByTagName("w:sdt")[0]
        sdt.getElementsByTagName("w:id")[0].setAttribute("w:val", str(siguiente_id))
        siguiente_id += 1
        fila_modelo.parentNode.insertBefore(fila, anterior.nextSibling)
        anterior = fila
        nuevos.append(sdt)
    return nuevos


def _llenar_filas_numeradas(documento, controles, filas_del_formulario, textos, prefijo_etiqueta):
    sdts = [_verificar(controles, indice, "fila", etiqueta) for indice, etiqueta in filas_del_formulario]
    if len(textos) > len(sdts):
        sdts += _agregar_filas(documento, controles, filas_del_formulario, textos, prefijo_etiqueta)
    for sdt, texto in zip(sdts, textos):
        _llenar_texto(documento, sdt, texto)


def _casilla(controles, opciones, clave):
    """El control de la casilla que corresponde a `clave`, verificado contra su etiqueta; None si no hay opcion."""
    if clave not in opciones:
        return None
    indice, donde, esperado = opciones[clave]
    return _verificar(controles, indice, donde, esperado)


def _llenar_documento(documento, descriptivo):
    controles = list(documento.getElementsByTagName("w:sdt"))
    if len(controles) != _TOTAL_CONTROLES:
        raise RuntimeError(
            f"La plantilla del Descriptivo cambió: trae {len(controles)} controles y se esperaban {_TOTAL_CONTROLES}."
        )

    # Las filas extra se clonan primero, antes de tocar nada.
    funciones = [f.texto for f in descriptivo.funciones.all()]
    indicadores = [i.texto for i in descriptivo.indicadores.all()]
    _llenar_filas_numeradas(documento, controles, _FUNCIONES, funciones, "Responsabilidad")
    _llenar_filas_numeradas(documento, controles, _INDICADORES, indicadores, "Indicador")

    for campo, (indice, etiqueta) in _TEXTOS.items():
        valor = getattr(descriptivo, campo)
        sdt = _verificar(controles, indice, "fila", etiqueta)
        if valor and valor.strip():
            _llenar_texto(documento, sdt, valor)

    indice, etiqueta = _FECHA
    sdt = _verificar(controles, indice, "fila", etiqueta)
    if descriptivo.fecha_elaboracion:
        _llenar_fecha(documento, sdt, descriptivo.fecha_elaboracion)

    # Casillas de opcion unica / disponibilidad / varias (competencias, recursos).
    marcadas = []
    if descriptivo.edad_id:
        marcadas.append(_casilla(controles, _EDAD, descriptivo.edad.code))
    if descriptivo.disponibilidad_viajar is not None:
        marcadas.append(_casilla(controles, _VIAJAR, descriptivo.disponibilidad_viajar))
    if descriptivo.dias_por_laborar_id:
        marcadas.append(_casilla(controles, _DIAS, descriptivo.dias_por_laborar.code))
    if descriptivo.horario_id:
        marcadas.append(_casilla(controles, _HORARIO, descriptivo.horario.code))
    for competencia in descriptivo.competencias.all():
        marcadas.append(_casilla(controles, _COMPETENCIAS, competencia.code))
    for recurso in descriptivo.recursos.all():
        marcadas.append(_casilla(controles, _RECURSOS, recurso.code))
    for sdt in marcadas:
        if sdt is not None:
            _marcar(sdt)

    # Renglones "Otro: ______".
    for valor, indice_casilla in (
        (descriptivo.edad_otro, _OTRO_EDAD),
        (descriptivo.dias_por_laborar_otro, _OTRO_DIAS),
        (descriptivo.horario_otro, _OTRO_HORARIO),
    ):
        if valor.strip():
            parrafo = _ancestro(controles[indice_casilla], "w:p")
            _escribir_en_renglon_otro(documento, parrafo, "Otro:", valor)
    if descriptivo.competencias_otras.strip():
        parrafo = _parrafo_suelto(documento, _OTRAS_COMPETENCIAS)
        _escribir_en_renglon_otro(documento, parrafo, _OTRAS_COMPETENCIAS, descriptivo.competencias_otras)
    if descriptivo.recursos_otro.strip():
        indice_casilla, prefijo = _OTRO_RECURSO_JUNTO_A
        fila = _ancestro(controles[indice_casilla], "w:tr")
        parrafos = [p for p in _hijos(_hijos(fila, "w:tc")[-1], "w:p") if "_" in _texto_de(p)]
        if len(parrafos) != 1:
            raise RuntimeError("La plantilla del Descriptivo cambió: no se encontró el renglón 'Otro:' de recursos.")
        _escribir_en_renglon_otro(documento, parrafos[0], prefijo, descriptivo.recursos_otro)


def generar_word(descriptivo):
    """
    Devuelve (nombre_archivo, BytesIO) con el Descriptivo de Puesto oficial de
    GPA lleno con los datos de esta version.
    """
    with zipfile.ZipFile(PLANTILLA, "r") as origen:
        entradas = origen.infolist()
        comentario = origen.comment
        contenidos = {entrada.filename: origen.read(entrada) for entrada in entradas}

    documento = minidom.parseString(contenidos[_DOCUMENTO_XML])
    _llenar_documento(documento, descriptivo)
    contenidos[_DOCUMENTO_XML] = documento.toxml(encoding="UTF-8", standalone=True)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as destino:
        destino.comment = comentario
        for entrada in entradas:
            destino.writestr(entrada, contenidos[entrada.filename])
    buffer.seek(0)
    return f"{PLANTILLA.stem}_{descriptivo.pk}.docx", buffer
