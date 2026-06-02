# PoC técnica pre-código — VMS NTCIP 1203 v3 con Python + SNMP
# Versión 2

---

## 1. Cambios respecto a la versión 1

### 1.1 Escenarios eliminados

| ID v1 | Nombre | Motivo |
|---|---|---|
| POC-VMS-07 | Manual con expiración sobre schedule activo | Dependía del supuesto de que el scheduler retoma automáticamente tras expirar un manual. Supuesto descartado: el scheduler pierde el control cuando es desplazado por un manual y no lo recupera solo. El mecanismo estándar es `dmsEndDurationMessage`, verificado en POC-VMS-07 v2. |
| POC-VMS-08 | Estrategias de recuperación post-manual fallido | Dependía del mismo supuesto. La recuperación es responsabilidad de la plataforma, no del panel. |
| POC-VMS-17 | Soak test corto de schedule + manual | El criterio de PASS era que el scheduler retomara en 10/10 ciclos tras expirar el manual. Descartado por la misma razón. |

### 1.2 Escenarios modificados

| ID v1 | ID v2 | Cambio |
|---|---|---|
| POC-VMS-05 | POC-VMS-09 | Extendido para incluir múltiples Day Plans (Lun-Vie / Sáb-Dom). Necesario para validar el rediseño del modelo de schedules. |
| POC-VMS-00 al 16 | POC-VMS-01 al 20 | Reordenamiento y renumeración por grupos coherentes. Sin cambios de contenido salvo los indicados. |

### 1.3 Escenarios nuevos

| ID v2 | Nombre | Motivo |
|---|---|---|
| POC-VMS-03 | Capacidades reales del panel | Gap identificado en `panel_capability_profiles`: faltan `dmsMaxChangeableMsg`, `dmsMaxVolatileMsg`, `dmsMaxMultiStringLength`, `dmsMaxNumberPages` y límites del scheduler. |
| POC-VMS-07 | `dmsEndDurationMessage` — comportamiento real | Define qué hace el panel al expirar un manual y si la plataforma puede controlar ese OID. Crítico para el diseño de la transición manual → schedule. |
| POC-VMS-08 | Modelo de prioridades: menor, igual, mayor | Valida el comportamiento del panel ante activaciones con distintas prioridades. Determina el mapeo entre los 6 niveles funcionales de la plataforma y el rango 1–255 NTCIP. |
| POC-VMS-15 | `commLoss` y `dmsTimeCommLoss` | Crítico para definir el intervalo de polling. El Chainzone tiene `dmsTimeCommLoss=0` — hay comportamiento específico a verificar. |
| POC-VMS-17 | Reboot físico del panel | Modo de falla principal conocido: `timeBaseScheduleTableStatus=0` tras reboot. Documenta el estado post-reboot y la secuencia correcta de recuperación. |

### 1.4 Reordenamiento por grupos

| Grupo | Escenarios |
|---|---|
| Conectividad y descubrimiento | POC-VMS-01, 02, 03 |
| Mensajes: lectura y activación | POC-VMS-04, 05, 06, 07 |
| Prioridades | POC-VMS-08 |
| Schedule DEVICE | POC-VMS-09, 10, 11 |
| Divergencia y monitoreo | POC-VMS-12, 13, 14, 15 |
| Recovery y resiliencia | POC-VMS-16, 17 |
| Capacidades de hardware | POC-VMS-18, 19, 20 |

---

## 2. Resultado esperado de la PoC

La PoC debe producir tres entregables:

1. **Evidencia cruda**
   - archivos `.jsonl` por escenario;
   - valores SNMP leídos/escritos;
   - timestamps;
   - errores;
   - capturas visuales del panel cuando aplique.

2. **Reporte de resultado**
   - tabla por escenario con `PASS`, `FAIL`, `PARTIAL`, `QUIRK_PROVIDER` o `BLOCKED`;
   - observaciones;
   - impacto sobre el diseño.

3. **Matriz de decisión**
   - qué asunciones se confirman;
   - qué asunciones se rechazan;
   - qué comportamiento debe modelarse como específico de Daktronics/Chainzone;
   - qué debe modificarse en el documento técnico.

---

## 3. Formato de evidencia

Cada escenario debe generar un archivo `.jsonl` en:

```text
poc/snmp-vanguard/evidence/<scenario_id>_<timestamp>.jsonl
```

Cada línea debe tener este formato:

```json
{
  "scenario_id": "POC-VMS-08",
  "step": "activate_manual_higher_priority",
  "timestamp_utc": "2026-06-01T15:00:00.000Z",
  "operation": "SNMP_SET",
  "oid_name": "dmsActivateMessage",
  "oid": "1.3.6.1.4.1.1206.4.2.3.6.3.0",
  "snmp_type": "OctetString",
  "value_sent": "00B400B006000100000000000000",
  "value_read": null,
  "success": true,
  "error": null,
  "notes": "activePriority=180, runTimePriority=180, duration=indefinite"
}
```

Cada escenario debe terminar con un resumen:

```json
{
  "scenario_id": "POC-VMS-08",
  "result": "PASS",
  "summary": "Panel respects dmsMessageRunTimePriority in all tested combinations.",
  "design_impact": "Priority mapping confirmed. Constants fixed in DaktronicsVanguardProvider."
}
```

---

## 4. Escenarios de prueba

---

## GRUPO 1 — Conectividad y descubrimiento

---

### POC-VMS-01 — Conectividad SNMP base

#### Para qué sirve

Confirmar que el panel responde a SNMP con la versión y credenciales configuradas. Es el primer paso obligatorio antes de cualquier otro escenario. Si este falla, ninguno de los siguientes puede ejecutarse.

#### Cómo se verifica

```bash
python -m scenarios.poc_01_connectivity \
  --config config/panel.chainzone.lab.yaml
```

#### Pasos

1. Leer `sysDescr`.
2. Leer `sysUpTime`.
3. Repetir 5 veces con intervalo de 5 segundos.
4. Registrar latencia de cada GET.
5. Registrar errores SNMP si existen.

#### Criterio de éxito

`PASS` si al menos 5/5 lecturas responden sin timeout.

---

### POC-VMS-02 — Descubrimiento y confirmación de OIDs NTCIP

#### Para qué sirve

Construir el mapa real de OIDs que se usará en el resto de la PoC. No todos los paneles exponen los mismos OIDs aunque sean NTCIP 1203 compliant — hay OIDs opcionales, OIDs propietarios del fabricante y OIDs con rutas distintas según firmware. Este escenario cierra ese mapa antes de escribir una sola línea de código de producción.

#### Cómo se verifica

```bash
python -m scenarios.poc_02_oid_map \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml
```

#### Pasos

1. Ejecutar WALK sobre ramas NTCIP conocidas.
2. Ejecutar GET sobre OIDs simbólicos ya conocidos.
3. Registrar `NoSuchObject`, `NoSuchInstance` y errores de tipo.
4. Completar `oids.ntcip1203.v3.yaml` con los OIDs numéricos confirmados.
5. Separar OIDs estándar NTCIP de OIDs propietarios Daktronics/Chainzone.

#### Resultado esperado

Mapa mínimo confirmado para: mensaje activo, activación, duración, prioridad runtime, schedule, reloj, estado técnico, brillo, gráficos.

#### Criterio de éxito

`PASS` si se pueden confirmar los OIDs necesarios para los escenarios POC-VMS-03 a POC-VMS-20.

---

### POC-VMS-03 — Capacidades reales del panel

#### Para qué sirve

Leer y registrar todos los límites operativos del panel que están ausentes en el `panel_capability_profiles` actual del diseño. Sin estos valores no se puede validar correctamente al sincronizar un schedule (¿cuántos Day Plans caben?), al cargar un mensaje (¿cuántos bytes acepta el MULTI string?) ni al verificar compatibilidad. Es lectura pura — sin writes.

#### Cómo se verifica

```bash
python -m scenarios.poc_03_panel_limits \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml
```

#### Pasos

1. Leer `dmsMaxChangeableMsg` — slots máximos de mensajes changeable.
2. Leer `dmsMaxVolatileMsg` — slots máximos volatile.
3. Leer `dmsFreeChangeableMemory` — bytes libres disponibles.
4. Leer `dmsMaxMultiStringLength` — longitud máxima del string MULTI en bytes.
5. Leer `dmsMaxNumberPages` — páginas máximas por mensaje.
6. Leer `maxTimeBaseScheduleEntries` — entradas máximas en la tabla de schedules.
7. Leer `maxDayPlans` — Day Plans máximos soportados.
8. Leer `maxDayPlanEvents` — eventos máximos por Day Plan.
9. Leer `numActionTableEntries` — filas disponibles en la Action Table.
10. Comparar contra los valores conocidos del panel Daktronics Vanguard — documentar diferencias entre fabricantes.

#### Resultado esperado

Conjunto completo de límites operativos del panel listos para incorporar al `panel_capability_profiles`.

#### Criterio de éxito

`PASS` si todos los OIDs responden sin error y los valores son coherentes (> 0, dentro de rangos NTCIP).

#### Impacto en el diseño

Los valores se incorporan como campos faltantes en `panel_capability_profiles`: `max_changeable_messages`, `max_volatile_messages`, `max_multi_string_length`, `max_number_pages`, `max_schedule_entries`, `max_day_plans`, `max_day_plan_events`, `num_action_table_entries`.

---

## GRUPO 2 — Mensajes: lectura y activación

---

### POC-VMS-04 — Lectura del mensaje actualmente mostrado

#### Para qué sirve

Validar que el panel reporta por SNMP el mensaje que está mostrando. Es la base del mecanismo de divergencia: si la lectura del mensaje activo no es confiable, el `MessageMonitor` no puede funcionar.

#### Cómo se verifica

```bash
python -m scenarios.poc_04_read_current_message \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml
```

#### Pasos

1. Leer mensaje activo (`dmsMessageMultiString`).
2. Leer tipo de memoria del mensaje activo.
3. Leer número de mensaje activo.
4. Calcular hash canónico del MULTI leído.
5. Registrar evidencia visual del panel.
6. Comparar visual vs SNMP.

#### Resultado esperado

El texto mostrado visualmente coincide con el valor leído por SNMP, o se documenta la transformación aplicada por el firmware.

#### Criterio de éxito

`PASS` si la lectura SNMP es suficiente para implementar `MessageMonitor`.

---

### POC-VMS-05 — Activación manual básica

#### Para qué sirve

Validar que un mensaje enviado por SNMP se muestra en el panel. Es la operación más fundamental del sistema — si esto no funciona, nada de lo que viene después tiene sentido. También valida la secuencia completa de escritura: MULTI string → prioridad → duración → activación → verificación.

#### Cómo se verifica

```bash
python -m scenarios.poc_05_activate_manual \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --message MSG_EMERGENCY_MANUAL \
  --confirm-write
```

#### Pasos

1. Leer y guardar estado inicial del mensaje.
2. Escribir el MULTI del mensaje en slot changeable.
3. Escribir `dmsMessageRunTimePriority`.
4. Escribir duración si aplica.
5. Ejecutar activación via `dmsActivateMessage`.
6. Leer `dmsActivateMsgError` — verificar que es `none(2)`.
7. Esperar 3 segundos.
8. Leer mensaje activo.
9. Comparar hash esperado vs hash reportado.
10. Registrar evidencia visual.

#### Resultado esperado

El panel muestra el mensaje enviado y `dmsActivateMsgError = none(2)`.

#### Criterio de éxito

`PASS` si el mensaje se muestra y puede verificarse por SNMP.

---

### POC-VMS-06 — Expiración de manual sin schedule activo

#### Para qué sirve

Validar si el panel respeta la duración de un mensaje manual cuando no hay schedule activo. El diseño delega la expiración al panel — si el panel no la respeta, la plataforma debe implementar timers internos para cada manual, lo que cambia la arquitectura.

#### Cómo se verifica

```bash
python -m scenarios.poc_06_manual_duration_no_schedule \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --message MSG_EMERGENCY_MANUAL \
  --duration-seconds 60 \
  --confirm-write
```

#### Pasos

1. Asegurar que no hay schedule activo.
2. Activar mensaje manual con duración de 60 segundos.
3. Leer mensaje activo en T+0, T+30, T+60, T+75 y T+90.
4. Registrar `dmsMessageTimeRemaining` en cada lectura.
5. Registrar estado final — blank, default, último mensaje o estado propietario.

#### Resultado esperado

El mensaje deja de mostrarse al vencer la duración sin intervención externa.

#### Criterio de éxito

`PASS` si el manual expira localmente en el panel dentro del margen esperado.

#### Impacto si falla

Si falla, la plataforma debe implementar timers internos de expiración. El diseño de `Vms.Worker.Command` debe incluir un mecanismo de blanking explícito al vencer la duración esperada.

---

### POC-VMS-07 — `dmsEndDurationMessage` — comportamiento real

#### Para qué sirve

Determinar qué hace el panel cuando expira la duración de un mensaje manual. Por estándar NTCIP, al expirar se activa lo que esté configurado en `dmsEndDurationMessage`. Hay que verificar cuál es ese valor de fábrica, si la plataforma puede modificarlo, y si el scheduler retoma o queda detenido tras la expiración. Este escenario define exactamente qué responsabilidad recae en la plataforma y cuál en el panel.

#### Cómo se verifica

```bash
python -m scenarios.poc_07_end_duration_message \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --duration-seconds 60 \
  --confirm-write
```

#### Pasos

**Fase 1 — Valor de fábrica**

1. Leer `dmsEndDurationMessage` → registrar el valor actual.
2. Determinar a qué tipo de memoria y slot apunta.

**Fase 2 — Verificar si es escribible**

3. Intentar SET de `dmsEndDurationMessage` a blank (`memType=07, msgNum=01, CRC=0000`).
4. Leer de vuelta y verificar si el cambio se aplicó.
5. Registrar si acepta o rechaza el SET.

**Fase 3 — Comportamiento al expirar sin schedule**

6. Activar mensaje manual con `duration=60s`.
7. Esperar T+75s.
8. Leer `dmsMsgSourceMode` y mensaje activo.
9. Registrar qué muestra el panel al expirar.

**Fase 4 — Comportamiento al expirar con schedule activo**

10. Activar scheduler con prioridad 64.
11. Verificar `dmsMsgSourceMode = timebasedScheduler(9)`.
12. Activar mensaje manual con `duration=60s` y prioridad mayor (128).
13. Verificar que el panel muestra el manual.
14. Esperar T+75s.
15. Leer `dmsMsgSourceMode` → ¿vuelve a `timebasedScheduler(9)` o queda en `endDuration`?
16. Registrar si el scheduler retoma o si el panel queda en el estado de `dmsEndDurationMessage`.

#### Resultado esperado

Queda documentado el comportamiento del panel al expirar un manual, con y sin schedule activo. Se espera que el scheduler NO retome automáticamente — el panel ejecuta `dmsEndDurationMessage` y el scheduler queda detenido hasta que la plataforma lo reactive.

#### Criterio de éxito

`PASS` si el comportamiento al expirar es predecible y documentable.

`PARTIAL` si `dmsEndDurationMessage` no es escribible pero el comportamiento por defecto es aceptable.

`FAIL` si el comportamiento al expirar es indefinido o no verificable por SNMP.

#### Impacto en el diseño

Si el scheduler no retoma (resultado esperado): confirma que `Vms.Worker.State` debe detectar la expiración del manual y disparar reactivación explícita del scheduler via `SyncSchedule`. Si `dmsEndDurationMessage` no es escribible: se documenta el valor de fábrica en `model_types.model_config`.

---

## GRUPO 3 — Prioridades

---

### POC-VMS-08 — Modelo de prioridades: menor, igual, mayor

#### Para qué sirve

Validar el comportamiento del panel ante activaciones con distintas prioridades respecto al mensaje activo. El modelo de convivencia manual+schedule de la plataforma depende de que el panel respete `dmsMessageRunTimePriority`. Este escenario determina el mapeo correcto entre los 6 niveles funcionales de la plataforma (`INFORMATIVE` a `AUTHORITY`) y el rango 1–255 del panel, y confirma que el panel rechaza o acepta cada combinación como el estándar especifica.

#### Cómo se verifica

```bash
python -m scenarios.poc_08_priority_model \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Mapeo propuesto a validar

| `priority_code` plataforma | `activePriority` NTCIP | `runTimePriority` NTCIP |
|---|---|---|
| `INFORMATIVE` | 32 | 32 |
| `NORMAL` | 64 | 64 |
| `MAINTENANCE` | 96 | 96 |
| `INCIDENT` | 128 | 128 |
| `EMERGENCY` | 192 | 192 |
| `AUTHORITY` | 254 | 254 |
| Scheduler (base) | 64 | 64 |

#### Pasos

**Fase 1 — Scheduler vs manual**

1. Activar scheduler con `activePriority=64`.
2. Verificar `dmsMsgSourceMode = timebasedScheduler(9)`.
3. Registrar `dmsMessageRunTimePriority` activo.

4. Intentar activar manual con `activePriority=32` (< scheduler).
   - Leer `dmsActivateMsgError`.
   - Verificar que el panel NO cambia de mensaje.

5. Intentar activar manual con `activePriority=64` (= scheduler).
   - Leer `dmsActivateMsgError`.
   - Verificar si el panel acepta o rechaza.

6. Intentar activar manual con `activePriority=128` (> scheduler).
   - Leer `dmsActivateMsgError`.
   - Verificar que el panel acepta y muestra el manual.

**Fase 2 — Manual vs manual**

7. Dejar activo el manual con `runTimePriority=128` del paso anterior.

8. Intentar activar nuevo manual con `activePriority=64` (< activo).
9. Intentar activar nuevo manual con `activePriority=128` (= activo).
10. Intentar activar nuevo manual con `activePriority=192` (> activo).

**Fase 3 — AUTHORITY resiste todo**

11. Activar mensaje `AUTHORITY` con `activePriority=254`, `runTimePriority=254`.
12. Intentar pisar con `activePriority=192`.
13. Intentar pisar con `activePriority=253`.
14. Intentar pisar con `activePriority=254`.
15. Intentar pisar con `activePriority=255`.

#### Tabla de resultados esperados

| Situación | `activePriority` vs activo | Resultado esperado |
|---|---|---|
| Manual intenta pisar scheduler | menor | `dmsActivateMsgError = priority(3)`, panel no cambia |
| Manual intenta pisar scheduler | igual | Panel acepta y muestra el manual |
| Manual intenta pisar scheduler | mayor | Panel acepta y muestra el manual |
| Manual intenta pisar manual | menor | `dmsActivateMsgError = priority(3)`, panel no cambia |
| Manual intenta pisar manual | igual | Panel acepta y muestra el nuevo manual |
| Manual intenta pisar manual | mayor | Panel acepta y muestra el nuevo manual |
| AUTHORITY es pisado con menor | menor o igual - 1 | `dmsActivateMsgError = priority(3)` |
| AUTHORITY es pisado con igual o mayor | igual o mayor | Panel acepta y muestra el nuevo mensaje |

#### Criterio de éxito

`PASS` si todos los casos de la tabla producen el resultado esperado.

`PARTIAL` si la mayoría funciona pero hay desvíos en casos límite — se documenta y se ajusta el mapeo.

`FAIL` si el panel ignora `dmsMessageRunTimePriority` — el modelo de convivencia manual+schedule requiere rediseño.

#### Impacto en el diseño

`PASS`: el mapeo propuesto se fija como constantes en `DaktronicsVanguardMultiV3Provider` y `ChainzoneMultiProvider`. `PARTIAL`: se ajusta el mapeo según el comportamiento real. `FAIL`: evaluar si desactivar/reactivar el scheduler alrededor de cada manual es viable operativamente.

---

## GRUPO 4 — Schedule DEVICE

---

### POC-VMS-09 — Carga de schedule DEVICE + múltiples Day Plans

#### Para qué sirve

Validar que el panel acepta programación local y que el rediseño del modelo de schedules es implementable. El modelo propuesto requiere múltiples Day Plans con distintos `day_of_week_mask` (ej: Lun-Vie y Sáb-Dom) apuntando a distintos conjuntos de eventos. Este escenario valida tanto la carga básica como la coexistencia de múltiples Day Plans activos simultáneamente.

#### Cómo se verifica

```bash
python -m scenarios.poc_09_schedule_device \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

**Fase 1 — Schedule básico**

1. Leer estado inicial del schedule.
2. Limpiar schedule anterior.
3. Cargar Action Table con al menos 2 mensajes.
4. Cargar Day Plan 1 con una ventana activa para los próximos minutos.
5. Cargar TimeBaseSchedule entry apuntando al Day Plan 1.
6. Activar scheduler con `memType=0x06`.
7. Leer `dmsMsgSourceMode` → debe ser `timebasedScheduler(9)`.
8. Esperar entrada de ventana.
9. Leer mensaje activo y verificar que es el esperado.

**Fase 2 — Múltiples Day Plans**

10. Cargar Day Plan 2 con eventos distintos.
11. Cargar segunda TimeBaseSchedule entry con `day_of_week_mask` distinto apuntando al Day Plan 2.
    - Day Plan 1: `day_of_week_mask = 126` (Lun–Vie).
    - Day Plan 2: `day_of_week_mask = 65` (Sáb–Dom).
12. Verificar que ambas entradas se almacenaron correctamente.
13. Cambiar el reloj del panel a un día hábil → verificar que ejecuta Day Plan 1.
14. Cambiar el reloj del panel a un día de fin de semana → verificar que ejecuta Day Plan 2.
15. Restaurar el reloj del panel al valor correcto.

#### Resultado esperado

El panel ejecuta el mensaje programado localmente y selecciona el Day Plan correcto según el día de la semana.

#### Criterio de éxito

`PASS` si el schedule se carga y ejecuta sin intervención posterior de la plataforma, y si el panel selecciona correctamente el Day Plan según `day_of_week_mask`.

`FAIL` en Fase 2 si el panel no soporta múltiples TimeBaseSchedule entries activas simultáneamente — el rediseño de schedules requiere workaround en el provider.

---

### POC-VMS-10 — Tipos de ventana soportados

#### Para qué sirve

Determinar qué tipos de ventana temporal soporta realmente el firmware. No todos los paneles implementan la totalidad del estándar NTCIP — algunos solo aceptan ventanas absolutas, otros soportan recurrencia semanal. Este escenario cierra la pregunta antes de diseñar la UI y el compilador de schedules.

#### Cómo se verifica

```bash
python -m scenarios.poc_10_schedule_window_types \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

1. Probar ventana `Absolute` (fecha y hora específica).
2. Probar ventana `RecurringDaily` (todos los días a la misma hora).
3. Probar ventana `RecurringWeekly` (días específicos de la semana).
4. Probar ventana que cruza medianoche.
5. Probar límite máximo de ventanas cargables simultáneamente.
6. Registrar errores por tipo de ventana.

#### Resultado esperado

Queda documentado qué tipos son soportados y cuáles no, con el error exacto retornado para cada caso no soportado.

#### Criterio de éxito

`PASS` si los tipos definidos para MVP son soportados o si las restricciones pueden modelarse en `model_types.model_config`.

---

### POC-VMS-11 — Re-sincronización de schedule existente

#### Para qué sirve

Validar que se puede reemplazar un schedule previamente cargado en el panel sin dejar restos del anterior. En operación normal, el operador puede modificar el schedule y la plataforma debe sincronizarlo sobre el panel que ya tiene uno cargado. Si el re-sync no es limpio, el panel puede acumular Day Plans o Action Table entries obsoletas.

#### Cómo se verifica

```bash
python -m scenarios.poc_11_resync_schedule \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

1. Cargar schedule A con mensajes y Day Plan definidos.
2. Confirmar ejecución del schedule A.
3. Cargar schedule B reemplazando A — nuevos mensajes, nuevo Day Plan.
4. Leer tabla de TimeBaseSchedule → verificar que no quedan entradas de A.
5. Leer Action Table → verificar que no quedan acciones de A.
6. Leer Day Plan → verificar que no quedan eventos de A.
7. Confirmar que B se ejecuta correctamente.

#### Resultado esperado

El panel queda con la programación nueva y sin restos de la anterior.

#### Criterio de éxito

`PASS` si el re-sync es determinístico y no acumula entradas obsoletas.

---

## GRUPO 5 — Divergencia y monitoreo

---

### POC-VMS-12 — Expected vs reported sin plataforma

#### Para qué sirve

Validar el núcleo del modelo de divergencia sin base de datos ni workers — con un script Python standalone. Si este algoritmo no funciona con datos reales del panel, el `MessageMonitor` no puede implementarse. Es el test más directo de la hipótesis central del diseño de monitoreo.

#### Cómo se verifica

```bash
python -m scenarios.poc_12_expected_vs_reported \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --expected-message MSG_NORMAL_SCH
```

#### Pasos

1. Definir expected local en archivo JSON.
2. Leer reported desde el panel via SNMP.
3. Calcular `expected_hash` (SHA-256 del MULTI string normalizado).
4. Calcular `reported_hash`.
5. Clasificar:
   - `IN_SYNC` si coinciden;
   - `DIVERGENT` si no coinciden;
   - `UNKNOWN` si no se pudo leer.
6. Simular un cambio externo en el panel y verificar que el script lo detecta como `DIVERGENT`.

#### Resultado esperado

El algoritmo de comparación es viable con datos reales del panel y detecta divergencias en máximo un ciclo de lectura.

#### Criterio de éxito

`PASS` si se puede decidir `IN_SYNC` / `DIVERGENT` de forma confiable usando la lectura SNMP.

---

### POC-VMS-13 — Override externo / UNMANAGED

#### Para qué sirve

Validar que se puede detectar un cambio realizado fuera de la plataforma — por un técnico en campo vía consola local, o por otro sistema con acceso SNMP. Este es el caso de uso real de la ruta 102: el técnico puede cambiar el mensaje localmente y la plataforma debe detectarlo y marcarlo como `UNMANAGED` sin pisar el cambio automáticamente.

#### Cómo se verifica

```bash
python -m scenarios.poc_13_unmanaged_override \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --external-message MSG_LOW_MANUAL \
  --confirm-write
```

#### Pasos

1. Dejar expected local en blank, default o schedule conocido.
2. Activar un mensaje externo usando un script separado o consola del fabricante (simula técnico en campo).
3. Leer `dmsControlMode` → verificar si el panel cambió a modo local.
4. Leer mensaje activo desde el script de monitoreo.
5. Comparar con expected local.
6. Clasificar como `UNMANAGED` si no existe una intención local que explique el cambio.
7. Verificar que el script de monitoreo NO pisa el mensaje externo automáticamente.

#### Resultado esperado

El cambio externo se detecta como `UNMANAGED` en máximo dos ciclos de lectura. La plataforma no corrige automáticamente.

#### Criterio de éxito

`PASS` si se detecta el override y se clasifica correctamente sin intervención automática.

---

### POC-VMS-14 — Reloj del panel y drift

#### Para qué sirve

Validar si el reloj del panel es confiable para schedules DEVICE-only. Todo el modelo de scheduling autónomo depende de que el `controllerLocalTime` del panel sea correcto — un drift de minutos puede hacer que los eventos del Day Plan se disparen en el momento equivocado sin que ningún error SNMP lo indique.

#### Cómo se verifica

```bash
python -m scenarios.poc_14_clock_drift \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --samples 10 \
  --interval-seconds 60
```

#### Pasos

1. Leer `controllerLocalTime` y `globalTime`.
2. Comparar contra hora UTC del host.
3. Calcular drift con signo (panel - host).
4. Repetir 10 veces con intervalo de 60 segundos.
5. Registrar drift mínimo, máximo y promedio.
6. Ejecutar un schedule con un evento en los próximos minutos y medir la hora real de activación vs la hora configurada.

#### Resultado esperado

El drift es menor a 30 segundos o es estable y modelable (drift constante, no creciente).

#### Criterio de éxito

`PASS` si el drift no compromete la ejecución de schedules con granularidad de minutos.

---

### POC-VMS-15 — `commLoss` y `dmsTimeCommLoss`

#### Para qué sirve

Verificar el comportamiento del panel ante pérdida de comunicación prolongada. Crítico para definir el intervalo de polling: si el polling es más lento que `dmsTimeCommLoss`, el panel activa el mensaje de commLoss aunque el sistema esté funcionando normalmente. El Chainzone tiene `dmsTimeCommLoss=0` (deshabilitado) — hay que verificar qué implica eso en condiciones de campo con conectividad semi-estable.

#### Cómo se verifica

```bash
python -m scenarios.poc_15_comm_loss \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --offline-seconds 120
```

#### Pasos

**Fase 1 — Configuración actual**

1. Leer `dmsTimeCommLoss` → registrar valor (`0` = deshabilitado).
2. Leer `dmsCommunicationsLossMessage` → qué mensaje activaría si se habilitara.
3. Registrar estado del scheduler.

**Fase 2 — Con `dmsTimeCommLoss=0` (deshabilitado)**

4. Cortar comunicación SNMP por 120 segundos.
5. Restaurar comunicación.
6. Leer `dmsMsgSourceMode` → ¿el scheduler sigue activo?
7. Leer mensaje activo → ¿el panel mantuvo el mensaje del schedule?
8. Registrar comportamiento.

**Fase 3 — Con `dmsTimeCommLoss` habilitado (si es escribible)**

9. Intentar SET de `dmsTimeCommLoss` a 1 minuto.
10. Si acepta: cortar comunicación por 90 segundos.
11. Restaurar comunicación.
12. Leer `dmsMsgSourceMode` → ¿activó `commLoss(12)`?
13. Verificar si el scheduler retoma al restaurar comunicación o requiere reactivación.

**Fase 4 — Definición del intervalo de polling**

14. Con el valor de `dmsTimeCommLoss` confirmado, calcular el intervalo máximo de polling que no dispara commLoss.
15. Documentar la invariante: `polling_interval < dmsTimeCommLoss`.

#### Resultado esperado

Queda definido el intervalo de polling seguro y el comportamiento del panel ante desconexión prolongada.

#### Criterio de éxito

`PASS` si el comportamiento con commLoss es predecible y la plataforma puede garantizar que el intervalo de polling es menor al umbral.

#### Impacto en el diseño

Confirma o ajusta el intervalo de polling por defecto (30s en el diseño actual). Define si `dmsTimeCommLoss` debe leerse durante el onboarding y almacenarse en `panel_capability_profiles`.

---

## GRUPO 6 — Recovery y resiliencia

---

### POC-VMS-16 — Recovery tras pérdida de comunicación

#### Para qué sirve

Validar el comportamiento del panel y de la plataforma al recuperar comunicación después de un período offline. En campo con conectividad semi-estable (ruta 102), este es el caso de uso cotidiano: la conexión se corta y se recupera múltiples veces por día. Hay que entender exactamente en qué estado queda el panel y qué debe hacer la plataforma al reconectar.

#### Cómo se verifica

```bash
python -m scenarios.poc_16_recovery_after_offline \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --offline-seconds 360
```

#### Pasos

1. Dejar el panel en estado conocido con schedule activo.
2. Cortar conectividad de red o bloquear SNMP.
3. Mantener offline por menos de 300 segundos.
4. Restaurar conectividad.
5. Leer mensaje activo, `dmsMsgSourceMode`, `timeBaseScheduleTableStatus`.
6. Repetir con offline mayor a 300 segundos.
7. Comparar si el panel mantuvo mensaje, schedule y reloj en ambos casos.
8. Verificar si el scheduler sigue activo o requiere reactivación.

#### Resultado esperado

Se entiende qué debe hacer la plataforma al recuperar comunicación: revalidar estado, adoptar el mensaje actual, o requerir intervención humana.

#### Criterio de éxito

`PASS` si el estado reportado después del recovery permite tomar una decisión determinística en la plataforma.

---

### POC-VMS-17 — Reboot físico del panel

#### Para qué sirve

Documentar el estado exacto del panel después de un reboot físico y definir la secuencia de recuperación que debe ejecutar la plataforma al detectar un reset de `sysUpTime`. El modo de falla principal conocido del Chainzone/Daktronics es que `timeBaseScheduleTableStatus` vuelve a 0 tras un reboot — el scheduler se pierde. En campo con obra vial, los cortes de energía son frecuentes. Sin este escenario el sistema puede quedar mostrando el mensaje de `powerRecovery` indefinidamente sin que la plataforma lo detecte como problema.

#### Cómo se verifica

```bash
python -m scenarios.poc_17_reboot_recovery \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml
```

#### Pasos

**Fase 1 — Estado conocido pre-reboot**

1. Cargar schedule con al menos 2 Day Plans y mensajes en memoria changeable.
2. Activar scheduler.
3. Registrar `sysUpTime`, `dmsMsgSourceMode`, `timeBaseScheduleTableStatus`, mensaje activo, `dmsMessageRunTimePriority`.

**Fase 2 — Reboot y lectura inmediata**

4. Cortar alimentación del panel o usar reset del VFC.
5. Esperar reconexión SNMP.
6. Leer `sysUpTime` → confirmar que bajó respecto al valor registrado.
7. Leer `timeBaseScheduleTableStatus` → registrar valor (se espera 0).
8. Leer `dmsMsgSourceMode` → ¿`powerRecovery(10)`, `central(8)` o blank?
9. Leer mensaje activo → registrar qué muestra el panel.
10. Leer `dmsMessageRunTimePriority` del mensaje activo.

**Fase 3 — Qué persiste y qué se pierde**

11. Verificar si los mensajes changeable persisten → intentar activar un slot que existía pre-reboot.
12. Leer `dmsNumChangeableMsg` → ¿cuántos mensajes quedan?
13. Leer Day Plans, TimeBaseSchedule entries y Action Table → registrar qué persiste.

**Fase 4 — Secuencia de recuperación**

14. Si los mensajes persisten: intentar reactivar scheduler directamente con `memType=0x06`.
15. Si los mensajes se perdieron: recargar mensajes primero, luego reactivar scheduler.
16. Leer `timeBaseScheduleTableStatus` → debe volver a 1.
17. Leer `dmsMsgSourceMode` → debe ser `timebasedScheduler(9)`.
18. Verificar que el panel retoma el mensaje correcto según el horario.
19. Documentar la secuencia mínima necesaria para recuperación completa.

#### Resultado esperado

Queda documentado exactamente qué se pierde tras un reboot y cuál es la secuencia determinística de recuperación.

#### Criterio de éxito

`PASS` si la secuencia de recuperación es determinística y repetible en al menos 3 ciclos de reboot.

#### Impacto en el diseño

Confirma que la detección de `sysUpTime` reset en el polling debe disparar una secuencia de recuperación en `Vms.Worker.State`. Define si el `SyncSchedule` post-reboot debe incluir recarga de mensajes changeable o solo reactivación del scheduler. Documenta el comportamiento de `powerRecovery(10)` para el provider.

---

## GRUPO 7 — Capacidades de hardware

---

### POC-VMS-18 — Brillo

#### Para qué sirve

Validar si el control de brillo por SNMP es viable para MVP. El Daktronics Vanguard tiene escala invertida (0=100% brillo). Hay que confirmar si el Chainzone tiene el mismo comportamiento o si la escala es directa, para parametrizar correctamente el provider.

#### Cómo se verifica

```bash
python -m scenarios.poc_18_brightness \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --levels 20,50,80 \
  --confirm-write
```

#### Pasos

1. Leer brillo actual (`dmsIllumManLevel`).
2. Guardar valor inicial.
3. Escribir nivel 20. Leer y registrar resultado visual.
4. Escribir nivel 50. Leer y registrar resultado visual.
5. Escribir nivel 80. Leer y registrar resultado visual.
6. Verificar si la escala es directa o invertida.
7. Restaurar valor inicial.

#### Resultado esperado

El panel acepta SET de brillo y lo reporta correctamente. Queda documentado si la escala es directa (0=apagado, 100=máximo) o invertida (0=máximo, 100=apagado) para el Chainzone.

#### Criterio de éxito

`PASS` si los niveles se aplican y pueden verificarse por SNMP.

---

### POC-VMS-19 — Gráficos

#### Para qué sirve

Validar si la gestión de gráficos debe entrar al MVP o quedar para F-VMS.2. Los gráficos requieren carga de BMP, gestión de slots, verificación de CRC y compatibilidad con el MULTI tag `[g]`. Si el proceso es inestable o propietario, es más seguro excluirlo del MVP.

#### Cómo se verifica

```bash
python -m scenarios.poc_19_graphics \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --graphic ./assets/test.bmp \
  --slot 1 \
  --confirm-write
```

#### Pasos

1. Leer soporte de gráficos (`dmsGraphicMaxEntries`).
2. Leer cantidad de slots disponibles.
3. Cargar BMP compatible en slot 1.
4. Leer estado del slot → `graphicStatus`.
5. Referenciar gráfico desde un MULTI string con `[g1]`.
6. Activar mensaje con gráfico y verificar visualmente.
7. Leer CRC del gráfico cargado.
8. Limpiar slot o restaurar estado.

#### Resultado esperado

Se confirma si gráficos son confiables para el MVP o si deben quedar fuera del alcance inicial.

#### Criterio de éxito

`PASS` si se puede cargar, mostrar y verificar un gráfico de forma repetible.

---

### POC-VMS-20 — Capacidades MULTI del panel

#### Para qué sirve

Validar que el `model_type` y el `capability_profile` declarados no sobredeclaran capacidades respecto al firmware real. Un mensaje con un tag no soportado puede causar `genErr` o comportamiento silencioso. Esta es la base para construir el `MultiValidator` correcto para el Chainzone.

#### Cómo se verifica

```bash
python -m scenarios.poc_20_multi_capabilities \
  --config config/panel.chainzone.lab.yaml \
  --oids config/oids.ntcip1203.v3.yaml \
  --confirm-write
```

#### Pasos

1. Leer `dmsSupportedMultiTags` → bitmap de tags soportados.
2. Leer dimensiones del panel (`dmsSignWidth`, `dmsSignHeight`).
3. Leer soporte de color (`dmsColorScheme`).
4. Probar mensajes con: salto de línea, página nueva, justificación, flashing, `[mvt]`, gráfico, tag no soportado.
5. Registrar qué acepta (`dmsActivateMsgError = none(2)`) y qué rechaza para cada tag.
6. Verificar que un tag no soportado retorna error explícito (no silencioso).

#### Resultado esperado

Matriz real de capacidades MULTI del Chainzone, lista para construir el `VmsPanelCapabilityProfile` correcto.

#### Criterio de éxito

`PASS` si se puede construir un `capability_profile` conservador y correcto que no sobredeclara capacidades.
