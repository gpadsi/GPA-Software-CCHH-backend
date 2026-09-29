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

## 3. Frontend Flutter — estado actual

Las 8 fases del plan de frontend están construidas y verificadas:
autenticación/sesión/dashboard, organización/ubicaciones,
personas/empleados, posiciones/línea de reporte, horarios/catorcenas,
secciones placeholder (Licencias, Reclutamiento, Desempeño, Tiempo, Buzz
— solo `EmptyState`, sin backend todavía), y pulido/rendimiento
(animación de entrada en el Dashboard, accesibilidad, sin jank
detectable). 91 pruebas automatizadas, `flutter analyze` limpio.

**Pendiente, no por alcance sino por higiene de proyecto:** el directorio
del frontend no tiene repo git propio. Todo ese trabajo vive solo en
disco local, sin historial ni respaldo remoto.

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
- **`recruitment`** (vacantes/postulaciones/etapas) — existía en los dos
  repos abandonados. El frontend ya tiene el placeholder "Reclutamiento"
  esperando a que esto se decida construir.
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
- **`files` con validación de contenido real (WebP, firma de archivo)** —
  existía en ambos repos abandonados. `apps.core` ya tiene adjuntos
  genéricos (`Attachment`) pero sin esa validación específica.
