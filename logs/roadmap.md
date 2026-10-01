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

**Pendiente de construir cuando el usuario lo confirme** (anotado
2026-10-01, no empezar sin esa confirmación): un apartado para filtrar
por Puesto en el front — ligado a `HistorialPuesto` (backend, rama
`blindaje-historial-laboral-pablo`), que hoy solo guarda el historial sin
que nada en el front ni la API lo consuma todavía.

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
`TipoRequisicion.requiere_justificacion` — ver `logs/dev_log.csv` sesión 8
para el detalle. 14 pruebas nuevas, 203 en total.

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
- **Exportar con el formato oficial exacto, confirmado para los 3
  documentos** (2026-10-01): al terminar de capturar una Requisición o un
  Descriptivo de Puesto en la app, debe poder descargarse como el mismo
  archivo oficial de GPA (el `.xlsx` de Requisición o Reemplazo según
  `tipo`, o el `.docx` de Descriptivo de Puesto), lleno, para imprimir —
  sin rediseñarlo nunca.
  - Excel (Requisición/Reemplazo): `openpyxl` escribiendo sobre una copia
    de la plantilla oficial (ya se usa en el proyecto para los imports).
  - Word (Descriptivo de Puesto): necesita una librería nueva
    (`python-docx`, hoy no instalada) o manipular el XML directamente
    (igual que se hizo para leer el archivo en esta conversación). Los
    checkboxes de competencias (12) y recursos (10) son controles de
    contenido nativos de Word (`w:sdt`), no casillas de texto simples —
    hay que resolver cómo marcarlos programáticamente sin romper el
    documento; se resuelve en la Entrega 2 (cuando se construya
    `DescriptivoPuesto`), no es parte de la Entrega 1.
  - Las 3 plantillas oficiales hay que incorporarlas al repo (no quedarse
    solo en el `Downloads` local) como archivo versionado, no como dato
    de usuario en `media/`.
- **Prerrequisito de seguridad antes de guardar CV o documentos firmados
  en `Attachment`**: `nginx/capital_humano.conf` sirve `/media/` directo,
  sin pasar por los permisos de Django — hay que arreglarlo antes, no es
  parte del módulo en sí pero se vuelve urgente con este módulo.
- Las 90 Posición ya vacantes hoy no se les va a inventar firmas ni
  fechas de aprobación — se resuelve con un comando de solo lectura
  (mismo patrón que `reportar_altas_pendientes`) antes de decidir si se
  migran con una Requisición "sin aprobación digital" o se dejan fuera.

**Orden de entrega acordado:** 1) Requisición completa de punta a punta
(incluye el export a Excel y el fix de nginx) → 2) Descriptivo de Puesto
versionado → 3) Candidatos (opcional, ligero: nombre/contacto/etapa/
notas/CV vía `Attachment`).

**Anotado para después, no ahora:** en el organigrama del frontend, por
ahora solo mostrar la secuencia (quién reporta a quién), sin desplegar
todos los campos de cada nodo — evita que se vea saturado o duplicado.
Poder entrar al detalle de cada Posición desde ahí es un plan futuro.
- **`files` con validación de contenido real (WebP, firma de archivo)** —
  existía en ambos repos abandonados. `apps.core` ya tiene adjuntos
  genéricos (`Attachment`) pero sin esa validación específica.
