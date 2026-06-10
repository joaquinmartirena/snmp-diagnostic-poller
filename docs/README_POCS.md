# PoCs VMS NTCIP 1203 — Guía operativa

Esta guía cubre los **22 escenarios PoC** que el toolkit ejecuta sobre
paneles VMS/DMS reales para caracterizar su comportamiento a nivel del
protocolo NTCIP 1203 v03. No son tests internos: son pruebas contra
hardware en campo que producen **evidencia estructurada** (JSONL) usable
para decisiones de diseño del producto.

Esta es la **referencia operativa**. Para el contexto y la decisión de
diseño detrás de cada escenario, ver
[`Poc_VMS_SNMP_Python_v4.md`](Poc_VMS_SNMP_Python_v4.md).

---

## Tabla de contenidos

- [Modelo de ejecución](#modelo-de-ejecución)
- [Cómo correr](#cómo-correr)
- [Configuración por panel](#configuración-por-panel)
- [Layout de evidencia](#layout-de-evidencia)
- [Catálogo de los 22 escenarios](#catálogo-de-los-22-escenarios)
- [Hallazgos confirmados en campo](#hallazgos-confirmados-en-campo)
- [Apéndice: ritual NTCIP de carga + activación](#apéndice-ritual-ntcip-de-carga--activación)

---

## Modelo de ejecución

### Veredictos

| Veredicto | Significado |
|---|---|
| `PASS` | El escenario cumplió todos sus criterios. |
| `PARTIAL` | El escenario llegó parcialmente; el panel responde pero con desvíos documentables. |
| `QUIRK_PROVIDER` | El panel se comporta de forma propietaria pero clasificable; agregar override en el Provider. |
| `FAIL` | El escenario no pudo cumplir su criterio principal. Hay un problema de panel o de premisa. |
| `BLOCKED` | El escenario no llegó a ejecutarse — falta el doble gate de escritura, o el panel exige una acción física previa que no se realizó. |

### Modos de ejecución

| Modo | Cuándo |
|---|---|
| `AUTOMATIC` | Corre solo, sin intervención humana. |
| `REQUIRES_PHYSICAL` | Requiere intervención manual durante la ventana de observación (cambiar mensaje en consola del fabricante, cortar red, rebootear, etc.). |

### Doble gate de escritura

Los escenarios con `requires_write: true` solo ejecutan si las **dos**
condiciones se cumplen simultáneamente:

1. `confirm_write: true` en el bloque del device en `config.yaml`.
2. Flag `--confirm-write` en la línea del CLI.

Si falta alguna, el escenario queda `BLOCKED` antes de abrir el transporte
SNMP. Es defensa en profundidad: una flag accidental en el CLI no escribe
si el YAML no marcó al panel como "seguro para escribir", y al revés.

### Filtro `--automatic-only`

Excluye los `REQUIRES_PHYSICAL` (10, 12, 13) de la corrida. Útil para
batches no atendidos.

### Cleanup automático — `--cleanup-after-each`

Cuando se pasa este flag, después de cada scenario el runner ejecuta una
pasada de cleanup que:

1. Recorre los slots del rango configurado (default 235-255) y libera
   con `notUsedReq` **solo aquellos cuyo `dmsMessageOwner` sea
   `"itstoolkit-poc"`**. Si un slot tiene otro owner (operativo del
   cliente), NO se toca.
2. Resetea las filas del `dmsActionTable` que los PoCs hayan usado
   (default `action_index=[2]`) escribiendo un `MessageIDCode` de ceros.
3. Activa un mensaje `blank` (`memType=blank(7) / CRC=0`) para dejar la
   pantalla limpia.

Solo aplica si el doble gate de escritura está completo (mismo requisito
que los PoCs de escritura). El cleanup queda registrado como steps
adicionales (`cleanup.*`) en el JSONL del scenario que lo disparó.

Overrides en el YAML del device:

```yaml
cleanup_slot_range: [235, 255]      # rango inclusivo a escanear
cleanup_action_indexes: [2]         # action_indexes a resetear
```

---

## Cómo correr

### Listar escenarios disponibles

```bash
itstoolkit scenario list --family vms_ntcip1203
```

### Correr un escenario específico

```bash
itstoolkit scenario run --config config.yaml --scenario POC-VMS-05 --confirm-write
```

### Correr varios

`--scenario` es repetible:

```bash
itstoolkit scenario run --config config.yaml \
  --scenario POC-VMS-01 --scenario POC-VMS-02 --scenario POC-VMS-03 \
  --confirm-write
```

### Correr todos los AUTOMATIC

```bash
itstoolkit scenario run --config config.yaml --automatic-only --confirm-write
```

Esto ejecuta 18 escenarios (1-9, 11, 14-21) sobre cada device del YAML.
Salta los 3 `REQUIRES_PHYSICAL`.

> ⚠️ **POC-VMS-21 dura 1 h por default**. Si no querés que esté en la
> tanda batch, excluilo listando explícitamente los otros, o bajá su
> duración con `poc_21_duration_seconds: 60` en el YAML.

### Correr todos + limpiar entre cada uno

```bash
itstoolkit scenario run --config config.yaml \
  --automatic-only --confirm-write --cleanup-after-each
```

Al terminar el batch, todos los slots de prueba quedan liberados, el
`dmsActionTable` reseteado, y la pantalla en blanco.

### Correr los REQUIRES_PHYSICAL

Hay que listarlos explícitamente porque `--automatic-only` los excluye:

```bash
itstoolkit scenario run --config config.yaml --scenario POC-VMS-10
```

El escenario imprime una instrucción describiendo la acción manual esperada
y entra en una ventana de observación. Cuando detecta el cambio (o cuando
vence el timeout), produce el veredicto.

---

## Configuración por panel

Cada PoC con `requires_write: true` puede tener su slot / índice / nivel
preconfigurado para evitar colisiones con configuración operativa del
panel. Todos los knobs son opcionales — los defaults están elegidos en el
rango alto (slots 240-255, action_index 2) para no pisar la operación.

Las claves `poc_*` (y `expected_multi`, `cleanup_*`) no forman parte del
schema del adapter: el CLI las deja pasar tal cual desde el YAML hasta el
`ScenarioContext.device_config`. No requieren coerción de tipo ni
declaración previa — se leen con `ctx.device_config.get(...)` dentro de
cada scenario.

Ejemplo completo de un device:

```yaml
- name: dakt_0001
  type: VMS_NTCIP1203
  ip: 170.51.57.240
  port: 161
  community: administrator
  interval_seconds: 10
  # Mitad-config del doble gate.
  confirm_write: true

  # Overrides opcionales — solo si los defaults colisionan en este panel.
  # POC-05
  poc_05_slot: 250
  # POC-06
  poc_06_base_slot: 251
  poc_06_authority_slot: 252
  # POC-07
  poc_07_slot: 253
  poc_07_action_index: 2
  # POC-08
  poc_08_slot_a: 254
  poc_08_slot_b: 255
  poc_08_action_index: 2
  # POC-09
  expected_multi: "[jp3]ITSTK[nl]POC-VMS-05"
  # POC-10
  # (sin knobs adicionales)
  # POC-11
  poc_11_samples: 5
  poc_11_interval_seconds: 5
  poc_11_max_acceptable_drift_s: 30
  # POC-12 / POC-13 (ventanas para la intervención manual)
  poc_12_offline_seconds: 60
  poc_13_max_wait_seconds: 300
  # POC-14
  poc_14_levels: [20, 50, 80]
  # POC-15
  poc_15_max_slots_to_walk: 24      # subir para alcanzar slots altos (ej. 20)
  # POC-15B (carga BMP — requiere Pillow: pip install -e .[graphics])
  poc_15b_bmp_path: "assets/cruce_escolar.bmp"
  poc_15b_graphic_index: 20         # slot fijo; 0 = auto-elegir libre
  poc_15b_min_slot: 2               # si index=0, desde qué slot buscar
  poc_15b_graphic_number: 99
  poc_15b_graphic_name: "ITSTK-POC15B"
  poc_15b_activate: true            # true → activa [g99] tras cargar
  poc_15b_activate_slot: 244
  poc_15b_activate_priority: 255    # prioridad del visual (pisa el mensaje actual)
  # POC-16
  poc_16_slot: 240
  # POC-17
  poc_17_valid_slot: 246
  poc_17_empty_slot: 247
  poc_17_nonexistent_slot: 999
  # POC-18
  poc_18_slot: 248
  # POC-19
  poc_19_slot: 249
  # POC-20
  poc_20_test_slot: 245
  # POC-21 (endurance — ojo con la duración default de 1 h)
  poc_21_duration_seconds: 3600         # 1 h por default
  poc_21_max_consecutive_errors: 3
  poc_21_max_latency_ms: 500
  poc_21_max_cycle_drift_s: 0.5
  poc_21_slot_base: 235                 # ocupa 235-239
```

Ver `config.example.yaml` para los defaults mínimos.

---

## Layout de evidencia

Cada escenario produce un JSONL con un objeto por línea (un objeto por
step), terminando con un record de veredicto.

```
evidence/<family>/<device_name>/<run_ts>/<scenario_id>.jsonl
```

`<run_ts>` es **único por corrida del CLI** — todos los escenarios
ejecutados en la misma invocación quedan agrupados bajo la misma carpeta
por panel:

```
evidence/
└── vms_ntcip1203/
    ├── dakt_0001/
    │   └── 2026-06-08T15-55-44Z/
    │       ├── POC-VMS-01.jsonl
    │       ├── POC-VMS-02.jsonl
    │       └── ...
    └── chain_zone/
        └── 2026-06-08T15-55-44Z/
            └── ...
```

Forma de un record de step:

```jsonc
{
  "ts": "2026-06-08 12:55:44",
  "fields": {},
  "changes": [],
  "payload": {
    "scenario_id": "POC-VMS-05",
    "step": "verify.compare_multi",
    "timestamp_utc": "2026-06-08T15:55:44.123456Z",
    "operation": "SNMP_GET",
    "oid_name": "dmsMessageMultiString",
    "oid": "1.3.6.1.4.1.1206.4.2.3.5.8.1.3.3.250",
    "value_read": "[jp3]ITSTK[nl]POC-VMS-05",
    "success": true,
    "expected_sha256": "1930515e7ee9...",
    "reported_sha256": "1930515e7ee9..."
  }
}
```

> ⚠️ La evidencia contiene IPs, community strings y respuestas SNMP de
> hardware productivo. `evidence/` está en `.gitignore` y nunca debe
> commitearse.

---

## Catálogo de los 22 escenarios

### GRUPO 1 — Conectividad e inventario

#### POC-VMS-01 — Conectividad SNMP base

`AUTOMATIC` · read-only

Lee `sysDescr` + `sysUpTime` cinco veces con intervalo de 5 s. Es el primer
paso obligatorio: si falla, ningún otro PoC puede correr.

- **PASS**: 5/5 lecturas OK.
- **PARTIAL**: alguna lectura responde, otras no — conectividad intermitente.
- **FAIL**: 0/5 — el panel no responde, revisar IP/community.

#### POC-VMS-02 — Mapeo de OIDs NTCIP conocidos

`AUTOMATIC` · read-only

GET masivo de los OIDs principales esperados en NTCIP 1203 v3 (system
group + signControl + statError + globales NTCIP 1201). Reporta cuáles
responden.

- **PASS**: todos los OIDs críticos presentes.
- **PARTIAL**: algunos opcionales ausentes — `NoSuchObject`.
- **FAIL**: faltan críticos.

#### POC-VMS-03 — Capacidades escalares del panel

`AUTOMATIC` · read-only

GET masivo de capacidades (dimensiones, color, memoria, brillo, escalares
de fuentes/gráficos, escalares del scheduler NTCIP 1201). Pueblan el
`VmsPanelCapabilityProfile`.

- **PASS**: todas las 36 capacidades respondieron.
- **PARTIAL**: faltan opcionales (registradas como `unsupported`).
- **FAIL**: faltan críticas (dimensiones, memoria base).

#### POC-VMS-04 — Lectura del mensaje actualmente mostrado

`AUTOMATIC` · read-only

Lee el state control plane (`dmsControlMode`, `dmsMsgSourceMode`,
`dmsMsgTableSource`, `shortErrorStatus`), decodifica el `MessageIDCode`,
y hace GET del MULTI activo + SHA-256.

- **PASS**: MULTI activo leído y hasheado.
- **PARTIAL**: control plane OK pero MULTI no decodifica (panel sin
  mensaje válido en catálogo).
- **FAIL**: control plane no responde.

### GRUPO 2 — Activación

#### POC-VMS-05 — Activación manual básica

`AUTOMATIC` · **write**

Carga un MULTI en un slot `changeable` siguiendo el ritual NTCIP 1203 §A.3
(`modifyReq` → escribir contenido → `validateReq` → leer CRC) y lo activa
vía `dmsActivateMessage`. Es la operación más fundamental — si esto no
funciona, el resto de los PoCs de escritura no tiene sentido.

- **Slot default**: 250 (`poc_05_slot`).
- **MULTI de prueba**: `[jp3]ITSTK[nl]POC-VMS-05`.
- **PASS**: `dmsActivateMsgError = none(2)` + hash reportado == enviado.
- **PARTIAL**: `none(2)` pero el panel transforma el MULTI (QUIRK).
- **FAIL**: ritual de carga no llega a `valid` o activación rechazada.

#### POC-VMS-06 — Modelo de prioridades: manual vs manual

`AUTOMATIC` · **write**

Matriz de 7 casos sobre 2 mensajes base (priority 128 y AUTHORITY 254)
ejercitando `activatePriority` menor/igual/mayor al `runTimePriority`
activo. Determina el mapeo correcto entre los niveles funcionales de la
plataforma y el rango 1-255 del panel.

- **Slots default**: 251, 252.
- **PASS**: 7/7 casos respetan la prioridad.
- **PARTIAL**: ≥70% OK, ajustar mapeo.
- **FAIL**: panel ignora `dmsMessageRunTimePriority`.

#### POC-VMS-07 — Carga de schedule DEVICE (núcleo)

`AUTOMATIC` · **write**

Núcleo del scheduling NTCIP 1203: cargar `dmsActionMsgCode.<idx>` y
activar el scheduler con `memType=schedule(6) / msgNum=1 / CRC=0x0000`.
NO carga `timeBaseScheduleTable` ni `dayPlanTable` (NTCIP 1201) que
dependen del firmware.

- **action_index default**: 2 (no 1, para no pisar acción operativa).
- **PASS**: `dmsMsgSourceMode = timebasedScheduler(9)` + mensaje correcto
  en pantalla.
- **PARTIAL**: panel acepta el SET pero no cambia el `src_mode` (probable
  dayPlan vigente apunta a otra acción).

#### POC-VMS-08 — Re-sincronización de schedule

`AUTOMATIC` · **write**

Sobrescribe la misma fila del `dmsActionTable` con dos `MessageIDCode`
sucesivos (A→B) y verifica que el panel queda limpio. No son dos schedules
distintos: es la misma fila reescrita.

- **Slots default**: 254, 255 · **action_index**: 2.
- **PASS**: B se muestra y la fila ya no contiene MessageIDCode de A.
- **PARTIAL**: re-sync correcto pero el panel sigue mostrando A
  (cache del `currentBuffer`).
- **FAIL**: panel acumula referencias huérfanas.

### GRUPO 3 — Divergencia y monitoreo

#### POC-VMS-09 — Divergencia expected vs reported

`AUTOMATIC` · read-only

Núcleo del modelo de divergencia: compara `expected_multi` (config local)
contra el MULTI reportado por el panel, dos veces con 3 s entre lecturas.
Clasifica como `IN_SYNC` / `DIVERGENT` / `UNKNOWN`.

- **PASS**: clasificación consistente entre lecturas.
- **PARTIAL**: la clasificación oscila (cambio en vuelo).
- **FAIL**: no se pudo leer el MULTI activo.

#### POC-VMS-10 — Detección de override externo / UNMANAGED

`REQUIRES_PHYSICAL` · read-only

> ⚠️ Durante la ventana de 15 s, activá un mensaje desde la consola del
> fabricante, switch local del gabinete u otro cliente SNMP.

Detecta cualquier cambio externo (hash del MULTI, `msg_id`, `ctrl_mode`)
como evidencia de override.

- **PASS**: detectó cambio.
- **PARTIAL**: sin cambios en 15 s — el operador no intervino.

### GRUPO 4 — Resiliencia

#### POC-VMS-11 — Reloj del panel y drift

`AUTOMATIC` · read-only

Lee `globalTime` (NTCIP 1201) N veces y mide drift contra UTC del host.
Crítico para schedules DEVICE-only.

- **Defaults**: 5 muestras × 5 s, umbral aceptable 30 s.
- **PASS**: `|drift| ≤ umbral`.
- **PARTIAL**: drift alto pero estable (compensable en software).
- **FAIL**: drift creciente — schedules locales no viables.

#### POC-VMS-12 — Recovery tras pérdida de comunicación

`REQUIRES_PHYSICAL` · read-only

> ⚠️ Durante la ventana (default 60 s), cortá la red del panel
> (Ethernet/firewall/WAN) y restaurala antes del cierre.

Snapshot inicial → polling para detectar offline+recovery → snapshot final
→ diff campo a campo.

- **PASS**: detectó caída y recovery; tomó snapshot post.
- **PARTIAL**: no detectó caída (operador no intervino), o no se recuperó
  a tiempo.

#### POC-VMS-13 — Reboot físico del panel

`REQUIRES_PHYSICAL` · read-only

> ⚠️ Durante la ventana (default 300 s), cortá la alimentación del panel
> o ejecutá reset desde la consola del VFC.

Detecta el reboot por caída de `sysUpTime`. Snapshot pre/post para
documentar qué persiste y qué se pierde (modo de falla conocido:
`dmsMsgSourceMode = powerRecovery(10)`).

- **PASS**: detectó reboot y tomó snapshot post — hay insumo para diseñar
  la secuencia de recuperación.
- **PARTIAL**: no detectó reboot (operador no intervino).

### GRUPO 5 — Capacidades de hardware

#### POC-VMS-14 — Brillo: SETs de `dmsIllumManLevel` + escala

`AUTOMATIC` · **write**

Lee `dmsIllumManLevel`, fuerza `manualIndexed(6)`, escribe 3 niveles
(default 20/50/80), verifica readback, y **restaura el valor original**
al final (incluyendo `dmsIllumControl` si lo cambió).

- **PASS**: 3/3 niveles aceptados y reportados sin transformación
  (escala directa).
- **PARTIAL**: aceptados pero panel reporta otros valores — escala
  invertida o saturación.
- **FAIL**: 0/3 aceptados — control de brillo no viable por SNMP.

#### POC-VMS-15 — Gráficos: inventario y capacidades

`AUTOMATIC` · read-only

Inventario read-only del `dmsGraphicTable` (slots ocupados, dimensiones,
tipo, ID, status). NO carga BMPs — eso es POC-VMS-15B.

- **PASS**: walk consistente con `dmsNumGraphics`.
- **PARTIAL**: inconsistencia walk vs contador (QUIRK).
- **FAIL**: panel no soporta el grupo dmsGraphic.

#### POC-VMS-15B — Gráficos: carga real de un BMP al panel

`AUTOMATIC` · **write** · requiere `Pillow` (`pip install -e .[graphics]`)

Ejecuta el ritual completo NTCIP 1203 §4.3.2 para cargar un BMP al
`dmsGraphicTable`. Convierte el bitmap al formato que pide el panel
según `dmsColorScheme`:

| `dmsColorScheme` | Formato escrito | Bytes |
|---|---|---|
| `color24bit(4)` | B, G, R por pixel (orden NTCIP) | `w*h*3` |
| `monochrome8bit(2)` | Luminancia BT.601 1 byte/px | `w*h` |
| `monochrome1bit(1)` | 1 bit/px, MSB-first, row-major | `(w*h + 7) // 8` |

Pasos:

1. Validar capacidades (`dmsColorScheme`, `dmsGraphicMaxSize`,
   `dmsGraphicBlockSize`, dimensiones del panel).
2. Parsear BMP local + convertir al formato del panel.
3. Validar que `len(bitmap) ≤ dmsGraphicMaxSize` y dimensiones encajan.
4. Elegir slot: explícito (`poc_15b_graphic_index`) o auto (primer slot
   libre desde `poc_15b_min_slot`). Un slot está libre si su
   `dmsGraphicStatus` es `notUsed(1)` **o si la fila no existe todavía**
   (`NoSuchInstance`) — muchos agentes no materializan las filas del
   `dmsGraphicTable` hasta que se escriben.
5. State machine: `modifyReq → modifying →` escribir metadata
   (number, name, height, width, type, transparent) `→` escribir bitmap
   en blocks de `dmsGraphicBlockSize` bytes `→ readyForUseReq →
   readyForUse`.
6. Leer `dmsGraphicID` (CRC computado por el panel) — debe ser `≠ 0`.
7. **Opcional**: si `poc_15b_activate: true`, cargar un MULTI `[gN]`
   en un slot changeable y activarlo con prioridad `poc_15b_activate_priority`
   (default 255, para poder pisar el mensaje actual del panel) y ver el
   gráfico en pantalla.

Knobs (en el YAML del device):

```yaml
poc_15b_bmp_path: "assets/cruce_escolar.bmp"   # REQUIRED (relativo al cwd o absoluto)
poc_15b_graphic_index: 20         # slot fijo; 0 = auto-elegir libre
poc_15b_min_slot: 2               # si index=0, desde qué slot buscar (nunca el 1)
poc_15b_graphic_number: 99        # número MULTI ([g99])
poc_15b_graphic_name: "ITSTK-POC15B"
poc_15b_activate: true            # true → activa [gN] tras cargar
poc_15b_activate_slot: 244        # slot changeable del MULTI activador
poc_15b_activate_priority: 255    # prioridad del visual (255 pisa cualquier mensaje)
```

> **Nota sobre OIDs del `dmsGraphicTable`**: las columnas viven en
> `…3.10.6.1.<col>.<idx>` (la cadena ASN.1 incluye el `.1` del
> `dmsGraphicEntry`). El PDF las anota como `…3.10.6.<col>` omitiendo
> ese `.1` — esa anotación **no** es el OID accesible. Verificado contra
> firmware real.

Veredictos:

- **PASS**: llega a `readyForUse` con `dmsGraphicID ≠ 0`. Si
  `poc_15b_activate` está activo, el summary indica si se mostró en
  pantalla o por qué no (p.ej. `priority(3)` si había un mensaje de mayor
  prioridad y la prioridad del visual no alcanzó).
- **PARTIAL**: cargado pero status final no es `readyForUse` o CRC=0
  (panel acepta los SETs pero no valida — revisar formato).
- **FAIL**: SETs rechazados, no hay slot libre, o bitmap excede
  capacidades.
- **QUIRK_PROVIDER**: el primer SET (`modifyReq`) es rechazado — el panel
  declara gráficos pero los objetos del `dmsGraphicTable` son read-only
  en ese firmware.
- **BLOCKED**: falta `poc_15b_bmp_path`, el archivo no existe, o `Pillow`
  no está instalado.

### GRUPO 6 — Capacidades MULTI

#### POC-VMS-16 — Capacidades MULTI: declarado vs real

`AUTOMATIC` · **write**

Cruza el bitmap `dmsSupportedMultiTags` con una batería real de 14 MULTIs.
Distingue **over-declaration** (panel dice soportar un tag y lo rechaza con
`unsupportedTag(3)`) de **datos faltantes** (panel soporta el tag pero el
gráfico/fuente referido no existe — devuelve `graphicNotDefined(15)`
etc.).

- **Slot default**: 240.
- **PASS**: matriz observada = bitmap declarado.
- **QUIRK_PROVIDER**: 1-2 tags sobre-declarados (enmascarables en el
  provider del fabricante).
- **PARTIAL**: panel soporta más de lo declarado (bitmap conservador).
- **FAIL**: >2 tags sobre-declarados (bitmap no confiable).

#### POC-VMS-17 — Errores de activación: códigos de `dmsActivateMsgError`

`AUTOMATIC` · **write**

Provoca 4 errores de activación documentados en la norma y verifica el
código devuelto:

| Caso | Esperado |
|---|---|
| CRC incorrecto | `messageCRC(7)` |
| Slot `notUsed` | `messageStatus(4)` |
| Slot inexistente | `messageNumber(6)` |
| MULTI con sintaxis inválida | `syntaxMULTI(8)` |

- **Slots default**: 246 (válido), 247 (vacío), 999 (inexistente).
- **PASS**: 4/4 según norma.
- **QUIRK_PROVIDER**: panel responde con códigos distintos pero
  consistentes — mapear en el provider.
- **FAIL**: panel acepta una activación que no debería.

#### POC-VMS-18 — Errores de sintaxis MULTI por tipo

`AUTOMATIC` · **write**

Batería de 7 MULTIs sintácticamente inválidos. Para cada uno verifica
`dmsMultiSyntaxError` y la `dmsMultiSyntaxErrorPosition`. Algunos casos
aceptan dos códigos posibles según la spec.

- **Slot default**: 248.
- **PASS**: 7/7 retornan código compatible con la spec.
- **QUIRK_PROVIDER**: rechazos OK pero códigos no estándar.
- **FAIL**: panel acepta MULTIs inválidos.

#### POC-VMS-19 — Recuperación de slot tras escritura parcial

`AUTOMATIC` · **write**

Simula una escritura interrumpida (`modifyReq` + escribir parcial **sin**
`validateReq`) y prueba si `notUsedReq` recupera el slot y permite
re-escribirlo limpio.

- **Slot default**: 249.
- **PASS**: `notUsedReq` recupera y re-escritura llega a `valid`.
- **QUIRK_PROVIDER**: `notUsedReq` falla pero `modifyReq` directo
  recupera con overwrite.
- **FAIL**: slot bloqueado, requiere reboot.

#### POC-VMS-20 — Panel en `localMode`: detección y comportamiento

`AUTOMATIC` · **write**

Intenta forzar `dmsControlMode = local(2)` por SNMP. Si el panel lo
permite, ejercita las fases de polling read-only en local, intento de
activación (esperando `localMode(9)`), y restore al modo central
original.

- **Slot default**: 245.
- **PASS**: polling responde en local + activación retorna `localMode(9)`.
- **QUIRK_PROVIDER**: activación retorna otro código.
- **BLOCKED**: panel rechaza el SET por SNMP — el cambio requiere
  switch físico del gabinete (feature de seguridad esperada).

### GRUPO 7 — Endurance / scheduling client-side

#### POC-VMS-21 — Scheduling client-side: loop endurance de 5 mensajes

`AUTOMATIC` · **write** · **larga duración (default 1 h)**

Test de **endurance**: carga 5 MULTIs y los activa en loop con timings
`2/1/3/2/1 s` (ciclo de 9 s) durante una ventana sostenida. Por default
corre 1 hora ≈ 400 ciclos ≈ **2000 activaciones SNMP encadenadas**.

Distinto a POC-VMS-07/08 que ejercitan el scheduler INTERNO del panel:
acá medimos la capacidad de la **plataforma de comandar al panel desde
afuera** con timing preciso (caso real del worker `Vms.Worker.Schedule`).

Métricas:

- **Latencia de aplicación** (`latency_apply_ms`): tiempo entre el SET
  de `dmsActivateMessage` y el primer GET de `dmsMsgTableSource` que
  confirma el cambio.
- **Drift por ciclo** (`cycle_drift_s`): diferencia entre el tiempo real
  del ciclo y los 9 s esperados.
- **Cycles completados / activaciones totales / errores**.

Al cerrar, **activa un mensaje `blank`** (`memType=blank(7) /
msgNum=priority / CRC=0x0000`) para dejar el panel limpio.

- **Slots default**: 235-239.
- **Abort temprano**: 3 errores consecutivos → `FAIL` con causa
  documentada (panel degradado bajo carga).
- **PASS**: completó la ventana, latencia media < 500 ms, drift max
  < 0.5 s.
- **PARTIAL**: completó pero con timing fuera de umbral — worker debe
  asumir jitter.
- **FAIL**: panel rechaza tras X activaciones, sugiere back-off del
  worker.

> ⚠️ La duración default (1 h) es para uso real en sitio. Para smoke
> tests rápidos seteá `poc_21_duration_seconds: 60` en el YAML
> (~6 ciclos en 1 minuto).

---

## Hallazgos confirmados en campo

Resultados observados al correr la batería completa contra el panel
Daktronics Vanguard productivo (`170.51.57.240`):

| POC | Veredicto | Hallazgo |
|---|---|---|
| 01-09 | PASS | Conectividad, capacidades, control plane, ritual de carga y activación todos funcionan según norma. |
| 11 | PASS | `globalTime` drift estable < 2 s contra UTC. Schedules DEVICE viables. |
| 14 | PASS | Escala de brillo **directa** (no invertida como Vanguard antiguo). |
| 15 | PASS | 255 slots de gráficos disponibles, 8 cargados de fábrica. |
| 16 | QUIRK_PROVIDER | Bitmap declara `[mvt]` pero el panel rechaza con `unsupportedTag(3)`. → enmascarar `mvt` en el `VmsPanelCapabilityProfile` del Daktronics. |
| 17 | PASS | 4/4 códigos de error según norma. |
| 18 | PASS (post-fix) | 7/7 categorías de syntax error retornan código compatible, incluyendo posición precisa en bytes. |
| 19 | PASS | `notUsedReq` recupera el slot limpiamente. **Nota**: en una corrida previa parecía fallar — era el guion (`-`) del MULTI de recovery, no incluido en la fuente default del panel. |
| 20 | BLOCKED (by design) | Panel **rechaza** SET de `dmsControlMode=local(2)` por SNMP. Feature de seguridad — solo cambia con switch físico. Documentar como requisito operativo. |

Los `REQUIRES_PHYSICAL` (10, 12, 13) están pendientes de ejecución contra
panel real.

---

## Apéndice: ritual NTCIP de carga + activación

Los PoCs que escriben mensajes siguen el state machine estándar
NTCIP 1203 §A.3, encapsulado en
[`scenarios/_activation.py`](../itstoolkit/devices/vms_ntcip1203/scenarios/_activation.py).

```
┌─────────────────────────────────────────────────────────────┐
│ 1. SET dmsMessageStatus.x.y = modifyReq(6)                  │
│ 2. wait until dmsMessageStatus.x.y == modifying(3)          │
│ 3. SET dmsMessageMultiString.x.y = <MULTI>                  │
│    SET dmsMessageOwner.x.y       = "<owner>"                │
│    SET dmsMessageRunTimePriority.x.y = <priority>           │
│    SET dmsMessageBeacon.x.y      = 0                        │
│    SET dmsMessagePixelService.x.y = 0                       │
│ 4. SET dmsMessageStatus.x.y = validateReq(7)                │
│ 5. wait until dmsMessageStatus.x.y == valid(4)              │
│    (early-exit si pasa a error(5) — no esperamos timeout)   │
│ 6. GET dmsMessageCRC.x.y                                    │
│                                                             │
│ Activación:                                                 │
│ 7. SET dmsActivateMessage = MessageActivationCode(12 bytes) │
│    [duration:2 | priority:1 | memType:1 | msgNum:2 |        │
│     CRC:2 (del paso 6) | sourceAddress:4]                   │
│ 8. GET dmsActivateMsgError → debe ser none(2)               │
└─────────────────────────────────────────────────────────────┘
```

El builder del `MessageActivationCode` está verificado byte-a-byte contra
el ejemplo de la norma (NTCIP 1203 §5.1).
