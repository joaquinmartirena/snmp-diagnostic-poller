"""POC-VMS-15 — Gráficos: inventario y capacidades (read-only).

Valida si la gestión de gráficos debe entrar al MVP o quedar para F-VMS.2.
La spec original incluye carga de BMP — esa parte requiere un state
machine de ``dmsGraphicStatus`` (similar a dmsMessageStatus), división del
bitmap en bloques de ``dmsGraphicBlockSize``, cálculo de CRC y validación.
Es un PoC propio. **Este escenario es la vuelta de exploración previa**:

- Confirma capacidades escalares (algunas ya cubiertas por POC-VMS-03).
- Hace walk de ``dmsGraphicTable`` para listar los slots ocupados/libres.
- Lee metadata (nombre, dimensiones, tipo, ID/CRC, status) de cada slot
  ocupado.

Esto deja documentado **qué hay cargado en el panel hoy** y permite decidir
si el equipo del MVP necesita la operación de upload o si los gráficos
preexistentes alcanzan. La carga de BMP queda explícitamente fuera:

.. note::

   La carga real de un BMP se hará en **POC-VMS-15b** (a definir). Requiere:
   - parsear BMP a bitmap raw 1-bit/8-bit/24-bit según ``dmsColorScheme``,
   - dividir en bloques de ``dmsGraphicBlockSize`` y enviar
     ``dmsGraphicBitmapTable`` fila por fila,
   - manejar el state machine de ``dmsGraphicStatus`` (modifyReq → modifying
     → readyForUseReq → readyForUse).

Criterio:

- ``PASS`` si se pueden leer las capacidades + el walk de la tabla
  produce datos coherentes (slot count consistente con
  ``dmsNumGraphics``).
- ``PARTIAL`` si las capacidades responden pero el walk falla o devuelve
  inconsistencias.
- ``FAIL`` si las capacidades escalares no responden — el panel no
  soporta el grupo dmsGraphic.

Defaults:

    poc_15_max_slots_to_walk: 8  # cuántos índices del dmsGraphicTable leemos
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Optional

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_FAIL,
    STATUS_PARTIAL,
    STATUS_PASS,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)

from .. import oids

# Columnas del dmsGraphicTable (1.3.6.1.4.1.1206.4.2.3.10.6.1.x)
GRAPHIC_TABLE_BASE = f"{oids.DMS_BASE}.10.6.1"
GRAPHIC_COL_INDEX = f"{GRAPHIC_TABLE_BASE}.1"
GRAPHIC_COL_NUMBER = f"{GRAPHIC_TABLE_BASE}.2"
GRAPHIC_COL_NAME = f"{GRAPHIC_TABLE_BASE}.3"
GRAPHIC_COL_HEIGHT = f"{GRAPHIC_TABLE_BASE}.4"
GRAPHIC_COL_WIDTH = f"{GRAPHIC_TABLE_BASE}.5"
GRAPHIC_COL_TYPE = f"{GRAPHIC_TABLE_BASE}.6"
GRAPHIC_COL_ID = f"{GRAPHIC_TABLE_BASE}.7"
GRAPHIC_COL_TRANSPARENT_ENABLED = f"{GRAPHIC_TABLE_BASE}.8"
GRAPHIC_COL_TRANSPARENT_COLOR = f"{GRAPHIC_TABLE_BASE}.9"
GRAPHIC_COL_STATUS = f"{GRAPHIC_TABLE_BASE}.10"


class PocVms15Graphics(Scenario):
    id = "POC-VMS-15"
    name = "Gráficos: inventario y capacidades"
    description = (
        "Inventario read-only de gráficos cargados en el panel + capacidades "
        "escalares. La carga de BMP queda para POC-VMS-15b."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = False

    default_max_slots_to_walk: ClassVar[int] = 8

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        max_slots = int(
            ctx.device_config.get(
                "poc_15_max_slots_to_walk", self.default_max_slots_to_walk
            )
        )

        # Paso 1: capacidades escalares
        cap_oids = {
            "dmsGraphicMaxEntries": oids.DMS_GRAPHIC_MAX_ENTRIES,
            "dmsNumGraphics": oids.DMS_NUM_GRAPHICS,
            "dmsGraphicMaxSize": oids.DMS_GRAPHIC_MAX_SIZE,
            "availableGraphicMemory": oids.AVAILABLE_GRAPHIC_MEMORY,
            "dmsGraphicBlockSize": oids.DMS_GRAPHIC_BLOCK_SIZE,
        }
        vals, err = await ctx.snmp.get_many(list(cap_oids.values()))
        if err in ("TIMEOUT", "SNMP_ERROR"):
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"GET de capacidades de gráficos falló: {err}",
                error=err,
            )

        caps: Dict[str, Any] = {}
        missing: List[str] = []
        for name, oid in cap_oids.items():
            v = vals.get(oid)
            if v is None:
                missing.append(name)
                caps[name] = None
            else:
                try:
                    caps[name] = int(v)
                except Exception:
                    caps[name] = str(v)
        ctx.record_step(
            "capabilities",
            operation="SNMP_GET",
            value_read=caps,
            success=True,
            missing_optional=missing,
        )

        # Sin dmsGraphicMaxEntries no tiene sentido seguir.
        max_entries = caps.get("dmsGraphicMaxEntries")
        if not isinstance(max_entries, int) or max_entries <= 0:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Panel no reporta dmsGraphicMaxEntries usable "
                    f"({max_entries!r}). No soporta gráficos vía NTCIP."
                ),
                design_impact=(
                    "Gráficos quedan FUERA del MVP para este firmware. "
                    "Evaluar alternativa si el caso de uso los requiere."
                ),
            )

        # Paso 2: walk del dmsGraphicTable (limitado a max_slots o max_entries)
        slots_to_read = min(max_slots, max_entries)
        slots_found: List[Dict[str, Any]] = []
        slots_empty: List[int] = []
        for idx in range(1, slots_to_read + 1):
            row_oids = {
                "number": f"{GRAPHIC_COL_NUMBER}.{idx}",
                "name": f"{GRAPHIC_COL_NAME}.{idx}",
                "height": f"{GRAPHIC_COL_HEIGHT}.{idx}",
                "width": f"{GRAPHIC_COL_WIDTH}.{idx}",
                "type": f"{GRAPHIC_COL_TYPE}.{idx}",
                "id": f"{GRAPHIC_COL_ID}.{idx}",
                "status": f"{GRAPHIC_COL_STATUS}.{idx}",
            }
            row_vals, err = await ctx.snmp.get_many(list(row_oids.values()))
            if err in ("TIMEOUT", "SNMP_ERROR"):
                ctx.record_step(
                    f"row_{idx}",
                    operation="SNMP_GET",
                    success=False,
                    error=err,
                    slot=idx,
                )
                continue

            row: Dict[str, Any] = {"slot": idx}
            populated = False
            for k, o in row_oids.items():
                v = row_vals.get(o)
                if v is None:
                    row[k] = None
                else:
                    populated = True
                    row[k] = _coerce(k, v)

            if populated:
                slots_found.append(row)
                ctx.record_step(
                    f"row_{idx}",
                    operation="SNMP_GET",
                    value_read=row,
                    success=True,
                    slot=idx,
                )
            else:
                slots_empty.append(idx)

        # Veredicto
        num_graphics_reported = caps.get("dmsNumGraphics")
        slots_with_data = len(slots_found)
        consistent = (
            num_graphics_reported is None
            or not isinstance(num_graphics_reported, int)
            or slots_with_data >= min(num_graphics_reported, slots_to_read)
        )

        ctx.record_step(
            "summary",
            operation="VERIFY",
            value_read={
                "max_entries": max_entries,
                "slots_scanned": slots_to_read,
                "slots_with_data": slots_with_data,
                "slots_empty": slots_empty,
                "dmsNumGraphics_reported": num_graphics_reported,
                "walk_consistent_with_count": consistent,
            },
            success=True,
        )

        if not consistent:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Walk encontró {slots_with_data} slots con datos pero "
                    f"dmsNumGraphics={num_graphics_reported}. "
                    f"Inconsistencia entre tabla y contador."
                ),
                design_impact=(
                    "Confiar en el walk de la tabla, no en dmsNumGraphics. "
                    "Documentar el QUIRK del firmware."
                ),
            )

        if slots_with_data == 0:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PASS,
                summary=(
                    f"Panel soporta gráficos ({max_entries} slots, "
                    f"{caps.get('dmsGraphicMaxSize')} bytes/slot) pero NO "
                    f"hay gráficos cargados. La carga de BMP es POC-VMS-15b."
                ),
                design_impact=(
                    "El MVP puede asumir que los gráficos los carga el "
                    "fabricante o un tooling aparte; F-VMS.2 cubrirá upload."
                ),
            )

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"Panel soporta gráficos: {max_entries} slots máx, "
                f"{slots_with_data} cargados. "
                f"Inventario en evidencia."
            ),
        )


def _coerce(field: str, v: Any) -> Any:
    """Best-effort: int para campos numéricos, str para nombre/bytes."""
    if field in ("number", "height", "width", "type", "id", "status"):
        try:
            return int(v)
        except Exception:
            return str(v)
    # name: DisplayString
    try:
        if hasattr(v, "asOctets"):
            return bytes(v.asOctets()).decode("utf-8", errors="replace")
    except Exception:
        pass
    return str(v)
