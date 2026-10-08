# Capital Humano — Roadmap

Complementa [`dev_log.csv`](dev_log.csv) (qué pasó, paso a paso) con la
vista hacia adelante: qué ya quedó decidido y por qué, qué está construido
hoy, y qué falta — distinguiendo lo que falta **por dato** (esperando a
GPA) de lo que falta **por alcance** (ya prototipado en otro repo,
pendiente de acoplar) de lo que se descartó a propósito.

## 1. Qué es cada repo, en una línea

- [`capital-humano`](https://github.com/Pavloh-sudo/capital-humano) — el
  backend real, activo. Django + DRF + Postgres + Redis + Celery.
- `capital humano front` — el cliente Flutter que consume ese backend
  (local, sin repo git propio todavía).
- [`fastapi-gemini-capital-humano-demo`](https://github.com/Pavloh-sudo/fastapi-gemini-capital-humano-demo)
  — prototipo activo y **separado** de Permisos (Vale de Salida y
  Ausentismo) y Vacaciones, con un asistente de IA (Gemini) para
  solicitudes en lenguaje natural. No usa datos reales de GPA ni el
  esquema del backend final.
- [`ch-capital-humano`](https://github.com/Pavloh-sudo/ch-capital-humano) y
  [`gpa-capital-humano`](https://github.com/Pavloh-sudo/gpa-capital-humano)
  — dos intentos anteriores de backend, **abandonados**, sin actividad
  desde 2026-09-03 y 2026-09-14 respectivamente. Se mantienen en GitHub
  como referencia de qué se probó, no como código a mantener.

## 2. Backend final (`capital-humano`) — estado actual

**Construido y con datos reales de GPA:**

| App | Qué hace |
|---|---|
| `core` | Auditoría base (`BaseAuditModel`), catálogos con código autogenerado, adjuntos genéricos, permisos por rol, el check de campos temporalmente opcionales |
| `users` | `User` + 3 roles (Colaborador / Capital Humano / Admin), JWT, `/users/me/` |
| `organizations` | Niveles organizacionales, árbol de nodos (jerarquía real de Grupo GPA, sin multi-tenancy genérico), `Company` (12 empresas reales) |
| `locations` | Ubicaciones, naves, áreas |
| `persons` | Personas, contacto de urgencia, perfil médico |
| `positions` | Posiciones (845 reales), catálogo de puestos (248), línea de reporte (`HistorialReportaA`) |
| `employment` | Empleados (580+), contratos (467), historial salarial, `get_jefe()` |
| `schedules` | Catorcenas, tipos de horario, asignaciones de horario (431) y de ubicación |
| `imports` | Staging de datos crudos + comandos de importación/normalización/backfill |

135 pruebas automatizadas, `manage.py check`/`makemigrations --check`
limpios, CI en `.github/workflows/ci.yml` (postgres + redis reales, no
mocks; corre en cada push/PR a `main`).

**Decisiones de alcance ya tomadas (no las reabras sin una razón nueva):**

- Sin multi-tenancy: Grupo GPA es la única organización que existirá. Los
  dos intentos anteriores lo intentaron genérico (`tenancy` en
  `gpa-capital-humano`) y ambos se abandonaron — la jerarquía fija fue
  más simple de razonar y de importar contra datos reales.
- `Company` es un expediente aparte de `OrganizationNode` (no fusionados)
  porque el nodo organizacional siempre existe primero y el expediente
  legal (razón social/RFC) puede tardar en llegar.
- Nada de enums de Python para catálogos de negocio — todo tabla
  (`NamedCatalog`), para que RH pueda agregar un valor nuevo sin tocar
  código.
- Campos temporalmente opcionales solo mientras falte el dato real de
  GPA, nunca como diseño permanente — están listados a propósito en
  `apps/core/checks.py::_TEMPORARILY_OPTIONAL_FIELDS` (13 hoy) y
  `manage.py check` los recuerda en cada corrida hasta que se resuelvan.

**En una rama aparte, sin fusionar a `main` todavía**
(`blindaje-historial-laboral-pablo`) — responde a si un Empleado debería
depender de tener Contrato: hoy se puede borrar físicamente el único
Contrato de un Empleado o reasignarlo a otro sin que nada lo impida.
`apps.core.models.SoftDeleteModel` (aplicado a Empleado y Contrato) hace
que borrar cualquiera de los dos marque el registro en vez de borrarlo de
la tabla, y bloquea reasignar un Contrato existente a otro Empleado. Un
`UniqueConstraint` parcial garantiza a lo sumo un Contrato vigente por
Empleado y por Posición. `apps/employment/services.py`
(`dar_alta_nueva`/`dar_reingreso`) es el único camino soportado para dar
de alta o reingreso — Empleado y Contrato siempre juntos, en una sola
transacción — y `EmpleadoAdmin` ya exige un Contrato al crear un Empleado
nuevo (no al editar uno de los 121 pendientes). Un comando de solo
lectura (`reportar_altas_pendientes`) reporta esos 145 pendientes
(121 sin Contrato + 24 con todo cerrado) sin tocarlos. `HistorialPuesto`
(mismo patrón que `HistorialReportaA`) registra qué Puesto tuvo cada
Posición en el tiempo, para que un Contrato antiguo no muestre el Puesto
de hoy si se reclasificó después — con su backfill para las 845
Posiciones reales que ya existían (845 filas creadas, corrido contra la
base). Matriz de pruebas: concurrencia real (dos reingresos simultáneos
del mismo Empleado, uno pasa y el otro se rechaza limpio), reintentos,
auditoría de quién borra desde el admin, y compatibilidad con las
importaciones (ya resuelta de origen — `import_posiciones.py` ya
atrapaba `ValidationError` por fila sin tronar el resto).

**Ya resuelto (GPA confirmó 2026-09-30):** "activo" cuenta desde que la
persona EMPIEZA a trabajar, no desde que se registra el alta; el día
exacto de la baja ya NO cuenta como activo; y nunca puede haber dos
contratos activos al mismo tiempo (confirma que el `UniqueConstraint`
global, sin acotar por empresa, estaba bien). `ContratoQuerySet.
vigentes_en()`/`vigentes_hoy()` centraliza esta regla; `get_contrato_activo()`
y `get_jefe()` ya la usan. Verificado contra la base real: no cambia
ninguna respuesta actual (0 Contrato con fecha de ingreso o de baja a
futuro hoy) — solo importa para datos nuevos.

**Sigue sin decidir:** si la API pública también debe exigir Contrato al
crear un Empleado — hoy solo el admin lo exige.

**Anotado para el futuro (2026-10-01, no es inmediato):** RRHH
comentó que SÍ podría existir el caso de alguien con Contrato activo en
dos empresas del grupo al mismo tiempo, de forma temporal — mientras hace
un "servicio"/préstamo a otra empresa del grupo, no como algo permanente.
Hoy el `UniqueConstraint` de `Contrato` (ver arriba) lo bloquea siempre,
sin importar la empresa. Es modificable pero no trivial — alcance
aproximado:
- Hoy la empresa de un Contrato no es un campo propio, se deduce
  indirectamente vía `Contrato.posicion.organization_node`. Para acotar
  la constraint "por empresa" en vez de global, lo más limpio es agregar
  un campo de empresa directo en Contrato (la constraint de Postgres no
  puede referenciar algo a dos saltos de FK de distancia).
- Faltaría una forma de distinguir un Contrato "normal" de uno de
  préstamo/comisión temporal (y probablemente exigirle fecha de término).
- `Empleado.get_contrato_activo()` y `get_jefe()` hoy asumen que una
  persona tiene A LO SUMO un Contrato activo — con dos simultáneos hay
  que decidir cuál cuenta como "el principal" para esas dos cosas.
No se toca nada de esto sin que el usuario lo pida explícitamente.

## 3. Frontend Flutter — estado actual

Las 8 fases del plan de frontend están construidas y verificadas:
autenticación/sesión/dashboard, organización/ubicaciones,
personas/empleados, posiciones/línea de reporte, horarios/catorcenas,
secciones placeholder (Licencias, Reclutamiento, Desempeño, Tiempo, Buzz
— solo `EmptyState`, sin backend todavía), y pulido/rendimiento
(animación de entrada en el Dashboard, accesibilidad, sin jank
detectable). 91 pruebas automatizadas, `flutter analyze` limpio.

**Diferido por el usuario (2026-10-05), no empezar sin que lo pida:** la vista
de tarjetas en móvil. Debajo de 640 px las tablas se desplazan en horizontal y
los íconos de acción de cada fila (ver, editar, eliminar) quedan fuera de
pantalla; la solución prevista es mostrar cada fila como una tarjeta con sus
acciones visibles. Afecta a todas las pantallas con tabla.

**Pendiente de construir cuando el usuario lo confirme** (anotado
2026-10-01, no empezar sin esa confirmación): un apartado para filtrar
por Puesto en el front — ligado a `HistorialPuesto` (backend, rama
`blindaje-historial-laboral-pablo`), que hoy solo guarda el historial sin
que nada en el front ni la API lo consuma todavía.

**Mejoras del front del 2026-10-02 y el 2026-10-05** (después de las 8 fases;
312 pruebas, ya no son 91): *fundamentos de diseño* (una sola confirmación de borrado,
formularios en panel lateral, esqueleto con brillo, una sola transición de
página, paleta más profunda "vino", sin modo oscuro), *búsqueda y orden en
tablas* (en el servidor en 8 listas, en el cliente en Puestos y Tipos de
horario) y el *paso 2*: el front conoce el rol (`SessionUser.canManageHr`, que
manda el servidor) y NO muestra botones de escritura a quien la API rechazaría
(un Colaborador ve todo en solo lectura); y Empleados (alta con buscador de
persona en el servidor, edición del número de nómina), Puestos y Tipos de
horario (crear, editar, desactivar), Empresas (crear con su nodo, editar datos
legales) y Organigrama (agregar unidad dentro de un nodo, editar, eliminar)
dejaron de ser de solo lectura. Un borrado bloqueado muestra el motivo que da
el servidor. **No se hizo a propósito:** borrar Empleados (la baja es cerrar el
contrato, y "Eliminar" invitaría a usarlo como si lo fuera), borrar
Puestos/Tipos de horario, borrar Empresas, y mover un nodo a otro padre o
cambiarle el nivel. **Sigue pendiente:** pantallas de Contrato (alta, baja,
reingreso), historial salarial y adjuntos; la vista de tarjetas en móvil (<640 px los
íconos de acción de cada fila quedan fuera de pantalla); ocultar del menú lo
que un Colaborador no puede usar (hoy solo se ocultan los botones de
escritura); y que `/users/me/` traiga el id del Empleado de la cuenta.

## 4. Lo que falta por DATO (esperando a GPA, no es trabajo de programar)

- `Company.legal_name` / `rfc` / `employer_registration` de las 12
  empresas — GPA no ha compartido ese expediente legal todavía.
- `Posicion.reports_to` — 0 de 845 posiciones reales lo tienen resuelto;
  la columna "Supervisión" de la sábana mezcla nombres de persona y de
  unidad sin confirmar cuál es cuál (`Posicion.supervision_texto` guarda
  el texto crudo mientras tanto). **Mecanismo ya listo (2026-09-29):**
  `Puesto.es_gerencia_de_unidad` (marcar a mano en el admin el Puesto que
  GPA confirme como "cabeza de la unidad") + el comando
  `backfill_reports_to_por_unidad` (`apps/positions`) resuelven solos
  quién es jefe de quién dentro de la misma Unidad de Negocio + Ubicación
  física — sin adivinar por texto ("Gerente de X" hoy son 9 roles
  funcionales distintos, no un jefe genérico de unidad, así que no se usó
  ese patrón). Hoy no marca ningún Puesto, así que no asigna nada
  todavía; corre solo cuando RH confirme cuál Puesto sí cumple ese rol.
- El resto de los 13 campos de `_TEMPORARILY_OPTIONAL_FIELDS` (CURP/NSS/
  RFC/fecha de nacimiento/género de Persona, número de nómina, puesto y
  área de Posición, nave de Área, catorcena de las asignaciones).
- 25 Contrato que el backfill de nombre dejó sin tocar a propósito por
  ambigüedad genuina (2 a 28 Posiciones candidatas idénticas) — quedan
  reportados en la salida del comando para revisión manual.

Nada de esto se resuelve inventando datos — se resuelve solo, sin tocar
código, en cuanto GPA suba una sábana más completa (los comandos de
import ya están escritos para conectarlo automáticamente).

## 5. Lo que falta por ALCANCE — Permisos y Vacaciones (prototipado en `fastapi-gemini-capital-humano-demo`)

El prototipo de FastAPI ya resolvió el **flujo** de dos módulos completos
que el backend Django todavía no tiene. Antes de portarlo, qué se
reutiliza tal cual y qué se descarta:

### Se reutiliza el diseño del flujo, no el esquema de datos

El prototipo usa su propio `Colaborador`/`Jefatura`/`UsuarioDemo` porque
nació sin conexión al backend real. El repo final ya resuelve todo eso
mejor:

| Prototipo FastAPI | Ya existe en `capital-humano` |
|---|---|
| `Colaborador` | `Empleado` / `Persona` |
| `Jefatura` (jefe↔colaborador manual) | `Posicion.reports_to` + `Empleado.get_jefe()` (ya calculado, falta que GPA confirme `reports_to`, ver §4) |
| `UsuarioDemo` con rol seleccionable | `User` + `UserRole` reales (JWT) |
| `PerfilColaborador` (correo/puesto/teléfono/fecha de ingreso) | ya cubierto por `Persona`/`Empleado`/`Posicion`/`Contrato` |

### Lo que sí es trabajo nuevo de verdad

- **App para el Vale de Salida y Ausentismo**: `ValePermiso` (folio, tipo
  — trabajo GPA / sin goce / IMSS / reposición de tiempo —, fecha/hora,
  motivo, adjunto, estado), `ValeEvento` (bitácora), aprobación
  secuencial jefe→Capital Humano reutilizando `Empleado.get_jefe()` en
  vez de una tabla de jefatura aparte.
- **App para saldos y solicitudes de vacaciones**: `VacationBalance`
  (estatutarios/acumulados/usados/reservados/disponibles) y
  `VacationEntitlementRule` (tabla de días por antigüedad, versionable
  por fecha — el prototipo ya la diseñó bien, es portable casi tal
  cual), `VacationRequest` con la misma aprobación secuencial.
- **Decisión pendiente, no técnica sino de producto**: ¿el asistente de
  Gemini (interpretación en lenguaje natural de fechas/intención) pasa
  al producto final, o el prototipo solo sirvió para validar el flujo de
  aprobación y el formulario normal ya es suficiente? El prototipo ya
  demostró que se puede separar limpio ("la IA interpreta, nunca decide
  ni modifica saldos").
- Portar `ConversationSession`/`ConversationMessage` solo si la decisión
  de arriba es "sí, se queda el chat".
- Las plantillas HTML del prototipo no se portan — esa parte ya la
  resuelve el frontend Flutter; del prototipo se reutiliza el modelo de
  datos y las reglas de negocio, no la vista.

## 6. Lo que se descartó a propósito (existía en los repos abandonados, no se está portando)

- **`evaluations`** (evaluaciones mensuales jefe↔empleado con rotación) —
  existía completo en `ch-capital-humano`. No hay pedido concreto todavía
  ni datos reales de GPA sobre este proceso.
- ~~`recruitment` (vacantes/postulaciones/etapas)~~ — ya no aplica: se
  decidió construir (ver §7), no se portó nada de los repos abandonados,
  se diseñó desde cero basado en los formularios reales de GPA.
- **`surveys`** (encuestas) — existía en `gpa-capital-humano`. Se
  relaciona con el placeholder "Buzz" del frontend, pero Buzz ahí es más
  bien un muro de comunicados, no encuestas — son dos cosas distintas.
- **`payroll`** — existía en `gpa-capital-humano`, nunca se llegó a
  llenar de lógica real. `HistorialSalarial` en `employment` ya cubre el
  registro de sueldo; una app de nómina completa es un dominio mucho más
  grande que no se ha pedido.
- **App de auditoría formal (`audit`) y notificaciones async
  (`notifications`)** — existían en `ch-capital-humano`. Hoy la
  auditoría vive como campos en cada modelo (`BaseAuditModel`), suficiente
  para lo que se ha pedido.

## 7. Reclutamiento / Vacantes — en construcción (rama `reclutamiento-vacantes-pablo`)

Basado en 3 documentos reales de GPA, ya copiados al repo en
`apps/recruitment/plantillas_oficiales/`: `FO-C0-CH-01_Requisición_de_Personal`,
`FO-C0-CH-08_Reemplazo_de_Personal` (casi idénticos — Reemplazo omite la
sección de justificación) y `FO-C0-CH-04_Descriptivo_de_puesto`.

**Ya construido (2026-10-01):** app `apps.recruitment` con `Requisicion` +
`AprobacionRequisicion` + los 4 catálogos nuevos + el flag
`TipoRequisicion.requiere_justificacion`; API + permisos (`IsOwnerOrGestionRRHH`,
nuevo en `apps/core/permissions.py` y reutilizable para futuros módulos
tipo Permisos/Vacaciones: cualquier autenticado crea y administra lo
suyo, Capital Humano/Admin administra todo, borrar queda solo para
ellos). Ver `logs/dev_log.csv` sesión 8 para el detalle. 26 pruebas
nuevas en total, 215 en el proyecto.

**Entrega 2 completa (2026-10-02):** 2.1 modelos, 2.2 API/permisos y 2.3
export a Word (el detalle de cada una está en este párrafo).
2.1 — `DescriptivoPuesto`
versionado (borrador editable → congelado inmutable; una sola versión
borrador por Posición; `vigente_de(posicion)`), `FuncionPuesto`,
`IndicadorDesempeno` (sin tope de filas, el formulario trae 5 y 3),
`ConformidadDescriptivo` (híbrida usuario/nombre a mano, solo sobre versión
congelada, ligada a la Persona cuando el rol lo exige) y 5 catálogos nuevos
sembrados del Word real. `services.crear_borrador` / `copiar_version`.
2.2 — API bajo `/api/v1/recruitment/`: `descriptivos` (con acciones
`crear-borrador`, `copiar`, `congelar` y `vigente?posicion=`; filtros por
posición y `congelado`), `conformidades-descriptivo` y 5 catálogos de solo
lectura. Permisos: cualquier usuario autenticado **lee** el Descriptivo
(describe la plaza, no a una persona); solo Capital Humano/Admin lo
**escribe** y registra conformidades; un Colaborador no ve las
conformidades dentro del detalle (no se expone quién firmó). Si más
adelante se quiere que cada quien vea solo el Descriptivo de su propia
Posición, es un cambio chico en el queryset. El Colaborador todavía no
puede "aceptar" desde su cuenta (hoy es solo lectura en todo el sistema).
Funciones/indicadores/casillas se editan en una sola llamada con listas
completas que reemplazan a las anteriores.
2.3 — export a Word: `GET /descriptivos/{id}/exportar-word/` (mismo permiso
que leer; sirve para un borrador o una versión congelada) →
`apps/recruitment/exports_word.py` llena el `.docx` oficial (FO-C0-CH-04)
editando solo `word/document.xml` dentro del paquete, sin `python-docx` ni
dependencias nuevas; encabezado, pie, estilos y glosario quedan idénticos a
la plantilla. Los 63 controles de contenido de Word se localizan por
posición y cada entrada del mapa trae la etiqueta que debe tener al lado,
que se verifica al exportar: si alguien cambia la plantilla, falla con un
mensaje claro en vez de escribir en el campo equivocado. Casillas marcadas
como lo hace Word (☒, fuente MS Gothic, `w14:checked=1`); texto escrito con
el estilo `Cuerpo` de la plantilla (no la cursiva gris del texto guía);
renglones "Otro: ____" reemplazados por el valor subrayado; fecha con su
`fullDate`; más de 5 funciones o 3 indicadores clonan la última fila.
Reglas (iguales a las del Excel): lo que no tiene dato se queda como la
plantilla (texto guía gris incluido), las firmas quedan en blanco y los
textos del formato ("Funciones y responsabilidades institucionales" y la
indicación de Recursos necesarios) no se tocan. Verificado abriendo el
resultado en Microsoft Word y renderizándolo a PDF. **Decisión abierta:**
una fila sin dato conserva su texto guía, y las responsabilidades 2 y 3 lo
traen como ejemplos ("Ejemplo de redacción correcta/incorrecta") que se
imprimirían; si se prefiere dejar en blanco las filas sin dato, es un
cambio chico.
Descarga desde el back sin frontend ni token (2026-10-02): el admin de
Django tiene la acción "Descargar Excel oficial" en Requisiciones y
"Descargar Word oficial" en Descriptivos de puesto (un archivo si se
selecciona uno, un ZIP si se seleccionan varios; lo que no se pueda generar
avisa en vez de tronar). Mismos archivos que `exportar-excel` /
`exportar-word` de la API. Excel verificado también abriéndolo en Microsoft
Excel. Archivos de ejemplo (uno real, tres de demostración) en
`docs/ejemplos_exportados/` (carpeta ignorada por git).
Listas separadas por tipo en el admin (2026-10-02): "Requisiciones de
Reemplazo" y "Requisiciones de Nueva Posición" son dos listas (modelos
proxy `RequisicionReemplazo` / `RequisicionNuevaPosicion`, misma tabla, sin
datos duplicados), cada una con su formulario oficial (FO-C0-CH-08 /
FO-C0-CH-01). El tipo se pone solo al crear y no se puede cambiar desde esa
lista (cambiarlo movería la requisición a la otra lista y a otro
formulario); "Requisiciones" sigue mostrando todas, de cualquier tipo, para
auditar. La justificación sigue siendo obligatoria solo en Nueva Posición.
Hoy: 39 de Reemplazo y 0 de Nueva Posición (las 29 posiciones de ese tipo
no se migraron por no tener justificación). Los modelos proxy crean sus
propios permisos de Django: un usuario de admin que NO sea superusuario
necesitaría que se los asignen.

**Búsqueda y orden en las listas (2026-10-02, para las tablas del front):**
`?search=` y `?ordering=` en 10 listas — Personas, Empleados, Posiciones,
Empresas, Ubicaciones, Naves, Áreas, Catorcenas y las dos Asignaciones. La
búsqueda ignora mayúsculas y acentos ("perez" encuentra "Pérez") con la
extensión `unaccent` de PostgreSQL (migración `core.0007`, "trusted" desde
PG13: no pide superusuario) y se combina por palabras (todas deben aparecer).
Solo busca y ordena por lo que la tabla muestra: NSS/RFC no se buscan ni se
ordenan. **Seguridad:** el `OrderingFilter` de DRF, sin `ordering_fields`,
deja ordenar por CUALQUIER campo del serializer (ordenar por un campo permite
inferir su contenido aunque no se muestre); aquí una vista que no declara sus
campos simplemente ignora `?ordering=` (`SafeOrderingFilter`). El orden agrega
`pk` como desempate para que paginar una columna con valores repetidos no
repita ni se salte filas. La búsqueda corre DESPUÉS del filtro por dueño, así
que un Colaborador solo encuentra lo suyo. El esquema OpenAPI anuncia los dos
parámetros solo en las 10 vistas que los soportan. Puestos y Tipos de horario
(catálogos que el front recibe completos) se buscan y ordenan en el cliente.
331 pruebas en el proyecto.

**Rol y escritura desde el front (2026-10-02, paso 2 del plan del front):**
`/users/me/` ahora trae `role` (`{code, name}`, o null si la cuenta no tiene
rol) y `can_manage_hr` (true para Capital Humano y Admin). Sale de la misma
función que usa la API para decidir si dejar escribir (`es_gestion_rrhh`), así
el front no repite la regla; una cuenta sin rol (p. ej. un superusuario recién
creado) recibe false y la API tampoco le deja escribir. **Puestos y Tipos de
horario** pasaron de solo lectura a crear/editar para Capital Humano/Admin
(`EditableCatalogViewSet`, `apps/core/viewsets.py`); NO se borran, porque hay
Posiciones y Asignaciones que los usan: lo que ya no se ocupa se desactiva con
`is_active`. El código se genera solo al crear y ya no cambia (solo lectura:
las importaciones lo usan para reconocer el puesto), y el nombre no puede
repetirse (sin distinguir mayúsculas) al crear o al renombrar. El serializer de
Puesto ahora expone `es_gerencia_de_unidad`: es el interruptor que el propio
modelo dice que RH marca a mano cuando GPA confirme qué puesto es "cabeza de la
unidad" (quien lo ocupe pasa a ser jefe de toda su unidad); sigue en false para
todos los puestos. **Hallazgo:** borrar algo que otro registro usa (FK
`PROTECT`) respondía **500** — verificado contra datos reales con un nodo con
hijos y una posición con contrato. Ahora responde **409** con el motivo
("No se puede eliminar porque todavía está en uso por: 4 Nodos
organizacionales, 1 Posición…", `apps/core/exceptions.py`, configurado como
`EXCEPTION_HANDLER`). Otro hallazgo: `Company.rfc` y `Empleado.work_number` son
únicos y opcionales, y un vacío `""` chocaba con otro vacío; ahora cualquier
vacío se guarda como NULL (`vacio_como_nulo`), igual que los datos reales
(razón social y registro patronal también). 348 pruebas en el proyecto.

**Pantallas de Reclutamiento en el front (2026-10-05, paso 3 del plan del
front):** `/reclutamiento` ya no es un marcador. Dos pestañas: **Requisiciones**
(lista con búsqueda, orden y filtros por estado y tipo; alta y edición en
panel; detalle con solicitud, perfil, compensación, suspensión y las cuatro
firmas de aprobación; descarga del Excel oficial) y **Descriptivos de puesto**
(lista con filtro Borradores/Congelados; alta de un borrador desde una
Posición; editor de página completa con las secciones del FO-C0-CH-04;
congelar, copiar a un borrador nuevo, descarga del Word oficial y
conformidades). Cualquier cuenta puede levantar una requisición y ve solo las
suyas; Capital Humano y Admin ven todas, registran las aprobaciones y editan
los descriptivos; un Colaborador consulta y descarga los descriptivos.
Decisiones y cambios del back que salieron de esto: **(1) hueco de
autorización cerrado:** `Requisicion.estado` no tenía restricción y cualquier
solicitante podía poner su propia requisición en «Autorizada» por la API; ahora
solo Capital Humano/Admin elige cualquier estado y el resto solo Borrador o
Pendiente de Autorización (si no manda estado, empieza en Borrador;
`ESTADOS_QUE_ELIGE_EL_SOLICITANTE`). **(2)** Posición, Requisición y Descriptivo
traen `etiqueta` / `posicion_etiqueta` ("Puesto — Unidad (Área)"), armada con
`select_related` (una Posición no tiene nombre propio), `solicitante` y
`creado_por` para saber quién la levantó y si la cuenta puede editarla;
`TipoRequisicion` expone `requiere_justificacion`; las conformidades traen
`persona_nombre`. **(3)** Requisiciones filtran por posición/estado/tipo y
buscan/ordenan solo por lo que muestra la tabla (la búsqueda de un Colaborador
corre después del filtro por dueño, no encuentra las ajenas); Descriptivos
buscan/ordenan por nombre, empresa, área, versión y fechas. **(4)**
`CORS_EXPOSE_HEADERS = ["Content-Disposition"]`: sin él el navegador esconde el
nombre oficial del archivo en las descargas. **(5)** `Persona.__str__` dejaba un
espacio doble sin apellido materno ("Torres  Ana"), que llegaba al nombre del
jefe y a la celda del Excel; tres pruebas viejas daban por bueno ese defecto.
En el front: filtros por campo en `TableQuery`, campo de fecha, campo de texto
multilínea/solo lectura, selector con búsqueda en el servidor reutilizable
(`SearchPickerField`; el de personas ahora lo usa), descarga de archivos en web
con Blob (`core/files`, nueva dependencia directa `web`) y el nombre del
archivo tomado del servidor. La tabla de requisiciones pone tipo y área bajo la
posición: con siete columnas los íconos de acción quedaban fuera de pantalla.
**No se hizo a propósito:** exportar desde la lista, aprobar desde la cuenta de
quien aprueba (hoy Capital Humano captura cada firma, digital o física), avisar
de cambios sin guardar al salir del editor, ni nada de Candidatos (pospuesto).
Pendiente heredado: la vista de tarjetas en móvil. 361 pruebas del back y 312
del front.

**Reutiliza sin tocar:** `Posicion.tipo_requisicion`/`estatus` (ya traen
Vacante Pendiente/Activa/Suspendida/Eliminada), `headhunter`,
`solicitante_vacante`, fechas de registro/autorización de vacante,
`Attachment` (hoy sin uso).

**Decisiones ya tomadas en la conversación:**
- `Requisicion` (app nueva `apps/recruitment`) con **su propio** `tipo`
  (no lee `Posicion.tipo_requisicion` — una misma Posición puede tener
  varias Requisiciones en su vida) y **su propio** `estado` (borrador →
  pendiente → autorizada/rechazada → en reclutamiento → cubierta/cancelada),
  independiente de `Posicion.estatus`. Restricción: una sola Requisición
  abierta a la vez por Posición (mismo patrón que `UniqueConstraint` de
  Contrato).
- `area_solicitante` es un campo NUEVO en `Requisicion` (texto libre por
  ahora) — confirmado que NO es lo mismo que `Posicion.area` (esa es la
  ubicación física: Ubicación→Nave→Área).
- Aprobación con `AprobacionRequisicion` (tabla hija, 4 etapas: Jefe
  Inmediato, Gerencia del Área, Dirección General/VP, Capital Humano), sin
  orden estricto entre etapas. Cada etapa guarda fecha + o bien un usuario
  del sistema (si se aceptó ahí) o un nombre capturado a mano + documento
  firmado adjunto (si fue en papel) — cubre ambos casos sin tener que
  elegir uno de antemano.
- Cualquier usuario autenticado puede CREAR una Requisición (no solo
  Capital Humano/Admin) — un Gerente/Director sigue siendo rol
  "Colaborador" en el sistema (no existe rol de gerencia aparte), así que
  el filtro real es el flujo de aprobación, no el permiso de creación.
  `created_by` ya registra quién la levantó, sin campo nuevo.
- `DescriptivoPuesto` ligado a **Posición** (no a Puesto — confirmado:
  Puesto es el catálogo de título reutilizable, hoy 248 Puesto para 845
  Posición reales; Posición es la plaza específica con su propia área,
  empresa y jefe). Versionado (mismo patrón que `HistorialPuesto`): cada
  versión queda congelada, la conformidad del colaborador se liga a la
  versión + la persona específica, se puede copiar una versión existente
  para editar.
- Catálogos confirmados directo del Word (sin inventar): `CompetenciaConductual`
  (12 valores) y `RecursoAsignado` (10 valores) — ambos con M2M desde
  `DescriptivoPuesto`.
- Pendiente de resolver con quien maneja nómina, no se inventa aquí: la
  relación entre sueldo mensual compuesto/bruto/neto de la Requisición.
- **Exportar con el formato oficial exacto:**
  - ~~Excel (Requisición/Reemplazo)~~ — **resuelto (2026-10-01)**:
    `apps/recruitment/exports.py` llena una copia de la plantilla oficial
    que corresponda según `tipo`, mapeada celda por celda contra los
    archivos reales. Modifica solo la hoja y sus estilos dentro del
    paquete XLSX, para conservar intactos encabezados/pies con imagen y
    configuración de impresión. Las zonas de firma quedan en blanco a
    propósito — es para imprimir y firmar a mano, no para simular una
    firma que no existe. Los campos que no viven en `Requisicion`
    (nombre de la vacante, unidad de negocio, empresa, puesto y nombre
    del jefe inmediato) se resuelven desde `Posicion` al momento de
    exportar, vacíos si falta cualquier eslabón — igual criterio que
    `Empleado.get_jefe()`. Expuesto en
    `GET /requisiciones/{id}/exportar-excel/`, mismo permiso que ver la
    Requisición. Verificado contra una Requisición real migrada.
  - ~~Word (Descriptivo de Puesto)~~ — **resuelto (2026-10-02)**: se
    manipula el XML directo (sin `python-docx`); las casillas y campos son
    controles de contenido de Word (`w:sdt`) y se llenan como lo hace
    Word. Ver el punto 2.3 de arriba.
- ~~**Prerrequisito de seguridad antes de guardar CV o documentos firmados
  en `Attachment`**: `nginx/capital_humano.conf` sirve `/media/` directo~~
  — **resuelto (2026-10-01)**: se quitó ese `location` de nginx y se
  agregó `AttachmentDownloadView` (único camino soportado para bajar un
  adjunto, mismo permiso que el resto de `Attachment`);
  `AttachmentSerializer.get_file_url` ya apunta ahí. 4 pruebas nuevas.
- ~~Las 90 Posición ya vacantes hoy no se les va a inventar firmas ni
  fechas de aprobación~~ — **resuelto (2026-10-01)**:
  `backfill_requisiciones_vacantes` migró 39 (las que ya tenían
  `tipo_requisicion` capturado y no exigían justificación). Las otras 51
  quedaron reportadas sin tocar — 36 porque la sábana nunca capturó
  `tipo_requisicion` para esa Posición, 15 porque son "Nueva Posición"
  (exige justificación) y esa justificación no existe en ningún lado de
  los datos reales. Esas 51 se quedan sin Requisición hasta que alguien
  la levante a mano con los datos que sí se sepan; el comando es
  idempotente, se puede volver a correr cuando GPA complete más datos.

**Orden de entrega acordado:** 1) ~~Requisición completa de punta a punta
(incluye el export a Excel y el fix de nginx)~~ — **completa (2026-10-01)**
→ 2) ~~Descriptivo de Puesto versionado~~ — **completa (2026-10-02)**
(modelos, API/permisos y export a Word) → 3) Candidatos
(opcional, ligero: nombre/contacto/etapa/notas/CV vía `Attachment`) —
**pospuesto por decisión del usuario (2026-10-02)**: se retoma más adelante,
no empezar sin que lo pida.

Falta solo el frontend: hoy todo esto se usa desde el admin de Django o
directo contra la API — el placeholder "Reclutamiento" del sidebar sigue
sin pantallas reales (ver Entrega de frontend, aún no agendada).

**Anotado para después, no ahora:** en el organigrama del frontend, por
ahora solo mostrar la secuencia (quién reporta a quién), sin desplegar
todos los campos de cada nodo — evita que se vea saturado o duplicado.
Poder entrar al detalle de cada Posición desde ahí es un plan futuro.
- **`files` con validación de contenido real (WebP, firma de archivo)** —
  existía en ambos repos abandonados. `apps.core` ya tiene adjuntos
  genéricos (`Attachment`) pero sin esa validación específica.

**R1 de Vacantes — selector de posición (2026-10-08).** Primera rebanada del plan
de UI de Vacantes. Se reprodujo el bloqueo de «Nuevo descriptivo» en el navegador: no era un fallo de
capas ni de clics sino falta de retroalimentación (nada al enfocar, ceros y
errores silenciosos, Enter sin efecto, homónimos idénticos y etiqueta no
buscable por su guion largo). Back: `GET /recruitment/posiciones-elegibles/` (no
oculta posiciones; vacantes sin trámite abierto primero; devuelve el trámite
abierto sin filtrar de quién es una requisición ajena). Front: selector con
sugerencias, estados «Buscando / Sin coincidencias / Reintentar», teclado y
«Continuar borrador». 19 pruebas nuevas en el back y 22 en el front; todo en
verde. **Sigue:** R2 (crear requisición o descriptivo desde Posiciones, también
de posiciones ocupadas), R3 (Requisición como página de trabajo; depende de
definir qué es «área solicitante» para RH), R4 (Descriptivo con secciones y
aviso de cambios en la posición) y R5 (movimiento y rendimiento, con medición
en modo profile). 

**R2 de Vacantes — entrada y relaciones (2026-10-08).** Segunda rebanada del plan de UI de Vacantes. Desde Posiciones, Capital Humano crea una requisición o un descriptivo con la posición ya elegida, y ambos formularios muestran una tarjeta con lo que se sabe de ella (puesto, empresa, unidad, área, estatus y a quién reporta; «Sin relación registrada» cuando falta) en lugar de pedir que se vuelva a capturar. Back: `GET /recruitment/posiciones-elegibles/<id>/?para=` devuelve esos datos con la misma privacidad del listado y un número fijo de consultas; el nombre de la persona que es jefe no se expone. Los descriptivos de posiciones ocupadas ya se podían crear y ahora hay una prueba que lo respalda. 8 pruebas nuevas en el back y 22 en el front; todo en verde. **Sigue:** R3 (Requisición como página de trabajo; depende de definir qué es «área solicitante» para RH), R4 y R5.
