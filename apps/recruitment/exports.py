# apps/recruitment/exports.py
# Llena las plantillas oficiales de GPA con los datos de una Requisicion --
# NUNCA cambia su diseño, solo escribe en las celdas de respuesta que el
# formulario real ya trae en blanco (mapeadas a mano leyendo
# FO-C0-CH-01/FO-C0-CH-08 con openpyxl, celda por celda, contra los
# archivos reales en plantillas_oficiales/). Las zonas de firma se dejan
# tal cual -- confirmado 2026-10-01: el exportado es para imprimir y
# firmar a mano, no para simular una firma que no existe.
import io
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from xml.dom import Node, minidom

from openpyxl.utils.datetime import to_excel

PLANTILLAS_DIR = Path(__file__).resolve().parent / "plantillas_oficiales"

_MARCA = "X"

_MAPA_REQUISICION = {
    "plantilla": PLANTILLAS_DIR / "FO-C0-CH-01_requisicion_de_personal_v6.xlsx",
    "campos": {
        "fecha_solicitud": "D1",
        "fecha_a_cubrir_vacante": "N1",
        "nombre_vacante": "D4",
        "area_solicitante": "M4",
        "unidad_negocio": "D5",
        "empresa": "M5",
        "puesto_inmediato_superior": "D6",
        "nombre_jefe_inmediato": "M6",
        "justificacion": "A9",
        "idiomas": "D14",
        "nivel_tabulador": "H16",
        "sueldo_mensual_compuesto": "N16",
        "sueldo_mensual_bruto": "D18",
        "sueldo_mensual_neto": "N18",
        "fecha_entrega_a_capital_humano": "P22",
        "motivo_suspension": "D30",
        "fecha_suspension": "D31",
    },
    "horario": {
        "8:00 - 17:45": "F12", "7:00 - 16:00": "I12", "15:00 - 24:00": "L12",
        "23:30 - 07:30": "O12", "Otro": "R12",
    },
    "disposicion_viajar": {True: "O14", False: "Q14"},
    # La casilla de marca de cada opción es un rango fusionado (G20:H20 /
    # K20:L20) -- se escribe en su celda ancla, la de más a la izquierda.
    "tipo_contrato": {"Planta": "G20", "Temporal": "K20"},
}

_MAPA_REEMPLAZO = {
    "plantilla": PLANTILLAS_DIR / "FO-C0-CH-08_reemplazo_de_personal_v4.xlsx",
    "campos": {
        "fecha_solicitud": "D1",
        "fecha_a_cubrir_vacante": "N1",
        "nombre_vacante": "D4",
        "area_solicitante": "M4",
        "unidad_negocio": "D5",
        "empresa": "M5",
        "puesto_inmediato_superior": "D6",
        "nombre_jefe_inmediato": "M6",
        "idiomas": "D11",
        "nivel_tabulador": "D13",
        "sueldo_mensual_compuesto": "N13",
        "sueldo_mensual_bruto": "D15",
        "sueldo_mensual_neto": "N15",
        "fecha_entrega_a_capital_humano": "P19",
        "motivo_suspension": "D27",
        "fecha_suspension": "D28",
    },
    "horario": {
        "8:00 - 17:45": "F9", "7:00 - 16:00": "I9", "15:00 - 24:00": "L9",
        "23:30 - 07:30": "O9", "Otro": "R9",
    },
    # Reemplazo de Personal NO trae la fila de Justificación -- no hay
    # entrada "justificacion" en "campos" de este mapa a propósito.
    "disposicion_viajar": {True: "O11", False: "Q11"},
    # A diferencia de la plantilla de Requisición, aquí la casilla de marca
    # de cada opción también es un rango fusionado (G17:H17 / K17:L17) --
    # hay que escribir en su celda ancla (la de más a la izquierda), no en
    # la celda vacía de al lado como en la otra plantilla.
    "tipo_contrato": {"Planta": "G17", "Temporal": "K17"},
}

# La clave es TipoRequisicion.code (confirmado contra la base real:
# "nueva-posicion" / "reemplazo").
MAPAS_POR_CODIGO_TIPO = {
    "nueva-posicion": _MAPA_REQUISICION,
    "reemplazo": _MAPA_REEMPLAZO,
}

_CAMPOS_FECHA = {
    "fecha_solicitud",
    "fecha_a_cubrir_vacante",
    "fecha_entrega_a_capital_humano",
    "fecha_suspension",
}

_HOJA_XML = "xl/worksheets/sheet1.xml"
_ESTILOS_XML = "xl/styles.xml"


def _hijos_elemento(nodo, nombre):
    return [
        hijo for hijo in nodo.childNodes
        if hijo.nodeType == Node.ELEMENT_NODE and hijo.tagName == nombre
    ]


def _celda(documento, referencia):
    for celda in documento.getElementsByTagName("c"):
        if celda.getAttribute("r") == referencia:
            return celda
    raise ValueError(f"La plantilla oficial no contiene la celda {referencia}.")


def _limpiar_valor(celda):
    if celda.hasAttribute("t"):
        celda.removeAttribute("t")
    for hijo in list(celda.childNodes):
        celda.removeChild(hijo)


def _escribir_valor(documento, celda, valor):
    _limpiar_valor(celda)
    if valor in (None, ""):
        return

    if isinstance(valor, (date, datetime)):
        elemento = documento.createElement("v")
        elemento.appendChild(documento.createTextNode(str(to_excel(valor))))
        celda.appendChild(elemento)
        return

    if isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        elemento = documento.createElement("v")
        elemento.appendChild(documento.createTextNode(str(valor)))
        celda.appendChild(elemento)
        return

    celda.setAttribute("t", "inlineStr")
    inline = documento.createElement("is")
    texto = documento.createElement("t")
    valor_texto = str(valor)
    if valor_texto != valor_texto.strip():
        texto.setAttribute("xml:space", "preserve")
    texto.appendChild(documento.createTextNode(valor_texto))
    inline.appendChild(texto)
    celda.appendChild(inline)


def _aplicar_estilo_fecha(documento_hoja, estilos_xml, referencias):
    """Clona el estilo visual de cada celda y cambia solo su formato de fecha."""
    if not referencias:
        return estilos_xml

    documento_estilos = minidom.parseString(estilos_xml)
    num_fmts = documento_estilos.getElementsByTagName("numFmts")[0]
    ids_existentes = [
        int(nodo.getAttribute("numFmtId"))
        for nodo in num_fmts.getElementsByTagName("numFmt")
    ]
    id_fecha = max([163, *ids_existentes]) + 1
    formato_fecha = documento_estilos.createElement("numFmt")
    formato_fecha.setAttribute("numFmtId", str(id_fecha))
    formato_fecha.setAttribute("formatCode", "dd/mm/yyyy")
    num_fmts.appendChild(formato_fecha)
    num_fmts.setAttribute(
        "count", str(len(num_fmts.getElementsByTagName("numFmt"))),
    )

    cell_xfs = documento_estilos.getElementsByTagName("cellXfs")[0]
    estilos_originales = _hijos_elemento(cell_xfs, "xf")
    estilos_fecha = {}
    for referencia in referencias:
        celda = _celda(documento_hoja, referencia)
        indice_original = int(celda.getAttribute("s") or 0)
        if indice_original not in estilos_fecha:
            nuevo_estilo = estilos_originales[indice_original].cloneNode(deep=True)
            nuevo_estilo.setAttribute("numFmtId", str(id_fecha))
            nuevo_estilo.setAttribute("applyNumberFormat", "1")
            estilos_fecha[indice_original] = len(_hijos_elemento(cell_xfs, "xf"))
            cell_xfs.appendChild(nuevo_estilo)
        celda.setAttribute("s", str(estilos_fecha[indice_original]))

    cell_xfs.setAttribute("count", str(len(_hijos_elemento(cell_xfs, "xf"))))
    return documento_estilos.toxml(encoding="UTF-8", standalone=True)


def _guardar_sobre_plantilla(ruta_plantilla, valores, selecciones, mapa):
    """
    Edita únicamente celdas dentro del paquete XLSX original. Así se
    conservan cabeceras/pies con imagen, configuración de impresión y
    cualquier parte de la plantilla que openpyxl no puede reescribir.
    """
    with zipfile.ZipFile(ruta_plantilla, "r") as origen:
        entradas = origen.infolist()
        comentario = origen.comment
        contenidos = {entrada.filename: origen.read(entrada) for entrada in entradas}

    documento = minidom.parseString(contenidos[_HOJA_XML])
    fechas_con_valor = []
    for campo, referencia in mapa["campos"].items():
        valor = valores.get(campo)
        _escribir_valor(documento, _celda(documento, referencia), valor)
        if campo in _CAMPOS_FECHA and valor not in (None, ""):
            fechas_con_valor.append(referencia)

    for opciones in (mapa["horario"], mapa["disposicion_viajar"], mapa["tipo_contrato"]):
        for referencia in opciones.values():
            _escribir_valor(documento, _celda(documento, referencia), None)
    for referencia, valor in selecciones.items():
        _escribir_valor(documento, _celda(documento, referencia), valor)

    contenidos[_ESTILOS_XML] = _aplicar_estilo_fecha(
        documento, contenidos[_ESTILOS_XML], fechas_con_valor,
    )
    contenidos[_HOJA_XML] = documento.toxml(encoding="UTF-8", standalone=True)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as destino:
        destino.comment = comentario
        for entrada in entradas:
            destino.writestr(entrada, contenidos[entrada.filename])
    buffer.seek(0)
    return buffer


def _empresa_de(organization_node):
    """Sube la jerarquía hasta el nodo de nivel Empresa (número=1); None si no se encuentra."""
    nodo = organization_node
    visitados = set()
    while nodo is not None and nodo.pk not in visitados:
        if nodo.level.numero == 1:
            return nodo
        visitados.add(nodo.pk)
        nodo = nodo.parent
    return None


def _jefe_inmediato(posicion):
    """
    (puesto_inmediato_superior, nombre_jefe_inmediato) -- vacío en
    cualquiera de los dos si falta un eslabón (sin reports_to, sin Puesto
    capturado, posición de jefe vacante); nunca se inventa, mismo criterio
    que Empleado.get_jefe().
    """
    jefe_posicion = posicion.reports_to
    if jefe_posicion is None:
        return "", ""
    puesto_nombre = jefe_posicion.puesto.name if jefe_posicion.puesto_id else ""
    contrato = jefe_posicion.contratos.vigentes_hoy().first()
    nombre = str(contrato.empleado.persona) if contrato else ""
    return puesto_nombre, nombre


def generar_excel(requisicion):
    """
    Devuelve (nombre_archivo, BytesIO) con la plantilla oficial de GPA que
    corresponde al tipo de la Requisición, llena con sus datos.
    """
    mapa = MAPAS_POR_CODIGO_TIPO.get(requisicion.tipo.code)
    if mapa is None:
        raise ValueError(f"No hay plantilla oficial para el tipo '{requisicion.tipo.name}'.")

    posicion = requisicion.posicion
    puesto_inmediato_superior, nombre_jefe_inmediato = _jefe_inmediato(posicion)
    empresa = _empresa_de(posicion.organization_node)

    def _monto(valor):
        return float(valor) if valor is not None else None

    valores = {
        "fecha_solicitud": requisicion.fecha_solicitud,
        "fecha_a_cubrir_vacante": requisicion.fecha_a_cubrir_vacante,
        "nombre_vacante": posicion.puesto.name if posicion.puesto_id else "",
        "area_solicitante": requisicion.area_solicitante,
        "unidad_negocio": posicion.organization_node.name,
        "empresa": empresa.name if empresa else "",
        "puesto_inmediato_superior": puesto_inmediato_superior,
        "nombre_jefe_inmediato": nombre_jefe_inmediato,
        "justificacion": requisicion.justificacion,
        "idiomas": requisicion.idiomas_requeridos,
        "nivel_tabulador": requisicion.nivel_tabulador,
        "sueldo_mensual_compuesto": _monto(requisicion.sueldo_mensual_compuesto),
        "sueldo_mensual_bruto": _monto(requisicion.sueldo_mensual_bruto),
        "sueldo_mensual_neto": _monto(requisicion.sueldo_mensual_neto),
        "fecha_entrega_a_capital_humano": requisicion.fecha_entrega_a_capital_humano,
        "motivo_suspension": requisicion.motivo_suspension,
        "fecha_suspension": requisicion.fecha_suspension,
    }
    selecciones = {}
    if requisicion.horario_a_cubrir_id:
        referencia = mapa["horario"].get(requisicion.horario_a_cubrir.name)
        if referencia:
            selecciones[referencia] = _MARCA

    if requisicion.disposicion_viajar is not None:
        referencia = mapa["disposicion_viajar"][requisicion.disposicion_viajar]
        selecciones[referencia] = _MARCA

    if requisicion.tipo_contrato_ofrecido_id:
        referencia = mapa["tipo_contrato"].get(requisicion.tipo_contrato_ofrecido.name)
        if referencia:
            selecciones[referencia] = _MARCA

    buffer = _guardar_sobre_plantilla(
        mapa["plantilla"], valores, selecciones, mapa,
    )

    nombre_archivo = f"{mapa['plantilla'].stem}_{requisicion.pk}.xlsx"
    return nombre_archivo, buffer
