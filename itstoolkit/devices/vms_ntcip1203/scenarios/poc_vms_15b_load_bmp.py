"""POC-VMS-15B — Carga real de un BMP al panel (state machine completo).

Complemento "activo" de POC-VMS-15 (inventario read-only). Ejecuta el
ritual completo NTCIP 1203 §4.3.2 para cargar un BMP al
``dmsGraphicTable``:

1. Validar BMP local + capacidades del panel (dimensiones máximas,
   color scheme soportado).
2. Convertir el bitmap al formato esperado según ``dmsColorScheme``
   (``color24bit`` → BGR per pixel; ``monochrome8bit`` → luminancia
   1 byte/px; ``monochrome1bit`` → 1 bit/px packed MSB-first).
3. Encontrar un slot libre (``dmsGraphicStatus = notUsed``) o usar el
   configurado.
4. ``modifyReq`` → ``modifying`` → escribir metadata (number, name,
   height, width, type, transparent) → escribir el bitmap en blocks de
   ``dmsGraphicBlockSize`` bytes → ``readyForUseReq`` → ``readyForUse``.
5. Leer ``dmsGraphicID`` (CRC computado por el panel) — debe ser ≠ 0.
6. (Opcional, si ``poc_15b_activate=true``) Cargar un MULTI ``[gN]`` en
   un slot changeable y activarlo para mostrar el gráfico en pantalla.

Pre-requisitos:

- ``Pillow`` instalado (``pip install -e .[graphics]``).
- ``poc_15b_bmp_path`` en el YAML del device — ruta absoluta al BMP.

Defaults (overridables por device):

    poc_15b_bmp_path: null                # REQUIRED — sin esto, BLOCKED
    poc_15b_graphic_index: 0              # 0 = auto-elegir slot libre
    poc_15b_graphic_number: 99            # número MULTI ([g99])
    poc_15b_graphic_name: "ITSTK-POC15B"
    poc_15b_activate: false               # si true, activa [gN] tras cargar
    poc_15b_activate_slot: 244            # slot changeable donde meter el MULTI

Veredicto:

- ``PASS``: gráfico cargado, llega a ``readyForUse`` y el panel reporta
  un CRC válido en ``dmsGraphicID``.
- ``PARTIAL``: gráfico cargado pero el panel no validó (CRC = 0 o
  status quedó en otro estado).
- ``FAIL``: panel no soporta gráficos / no hay slot libre / SET de
  bitmap rechazado / escritura interrumpida.
- ``BLOCKED``: ``poc_15b_bmp_path`` no configurado, archivo no
  existe, o ``Pillow`` no instalado.
"""

from __future__ import annotations

import os
from typing import Any, ClassVar, List, Mapping, Optional, Tuple

from pysnmp.proto.rfc1902 import Integer, OctetString

from itstoolkit.core.scenario import (
    EXEC_AUTOMATIC,
    STATUS_BLOCKED,
    STATUS_FAIL,
    STATUS_PARTIAL,
    STATUS_PASS,
    STATUS_QUIRK,
    Scenario,
    ScenarioContext,
    ScenarioResult,
)

from .. import decoders, oids
from . import _activation


# Mapping dmsColorScheme → dmsGraphicType compatible
COLOR_SCHEME_TO_GRAPHIC_TYPE = {
    oids.COLOR_SCHEME_MONOCHROME_1BIT: oids.GRAPHIC_TYPE_MONOCHROME_1BIT,
    oids.COLOR_SCHEME_MONOCHROME_8BIT: oids.GRAPHIC_TYPE_MONOCHROME_8BIT,
    oids.COLOR_SCHEME_COLOR_CLASSIC: oids.GRAPHIC_TYPE_COLOR_24BIT,  # fallback
    oids.COLOR_SCHEME_COLOR_24BIT: oids.GRAPHIC_TYPE_COLOR_24BIT,
}


class PocVms15BLoadBmp(Scenario):
    id = "POC-VMS-15B"
    name = "Gráficos: carga real de un BMP al panel"
    description = (
        "Carga un BMP al dmsGraphicTable siguiendo el state machine "
        "NTCIP 1203 §4.3.2. Convierte el bitmap al formato del panel "
        "(según dmsColorScheme) y verifica que llega a readyForUse con "
        "un CRC válido."
    )
    execution_mode = EXEC_AUTOMATIC
    requires_write = True

    default_graphic_index: ClassVar[int] = 0  # 0 = auto
    default_graphic_number: ClassVar[int] = 99
    default_graphic_name: ClassVar[str] = "ITSTK-POC15B"
    default_activate: ClassVar[bool] = False
    default_activate_slot: ClassVar[int] = 244
    # Prioridad alta por default: el visual debe poder pisar el mensaje
    # actual del panel. Bajala si querés respetar prioridades operativas.
    default_activate_priority: ClassVar[int] = 255

    async def run(self, ctx: ScenarioContext) -> ScenarioResult:
        # --- Pre-flight: PIL disponible ----------------------------------
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_BLOCKED,
                summary=(
                    "Pillow no instalado. Ejecutar "
                    "`pip install -e .[graphics]` y reintentar."
                ),
            )

        # --- Pre-flight: ruta del BMP ------------------------------------
        bmp_path = ctx.device_config.get("poc_15b_bmp_path")
        if not bmp_path:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_BLOCKED,
                summary=(
                    "Falta `poc_15b_bmp_path` en el YAML del device — "
                    "no hay BMP que cargar."
                ),
            )
        if not os.path.isfile(bmp_path):
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_BLOCKED,
                summary=f"BMP no encontrado en: {bmp_path}",
            )

        # --- Paso 1: capacidades del panel -------------------------------
        caps_oids = [
            oids.DMS_COLOR_SCHEME,
            oids.DMS_GRAPHIC_MAX_ENTRIES,
            oids.DMS_GRAPHIC_MAX_SIZE,
            oids.DMS_GRAPHIC_BLOCK_SIZE,
            oids.VMS_SIGN_HEIGHT_PIXELS,
            oids.VMS_SIGN_WIDTH_PIXELS,
        ]
        vals, err = await ctx.snmp.get_many(caps_oids)
        if err in ("TIMEOUT", "SNMP_ERROR"):
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"GET de capacidades de gráficos falló: {err}",
                error=err,
            )
        color_scheme = _safe_int(vals.get(oids.DMS_COLOR_SCHEME))
        max_entries = _safe_int(vals.get(oids.DMS_GRAPHIC_MAX_ENTRIES))
        max_size = _safe_int(vals.get(oids.DMS_GRAPHIC_MAX_SIZE))
        block_size = _safe_int(vals.get(oids.DMS_GRAPHIC_BLOCK_SIZE))
        sign_h = _safe_int(vals.get(oids.VMS_SIGN_HEIGHT_PIXELS))
        sign_w = _safe_int(vals.get(oids.VMS_SIGN_WIDTH_PIXELS))

        if not (color_scheme and max_entries and max_size and block_size):
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    "Panel no reporta capacidades de gráficos completas "
                    f"(scheme={color_scheme}, entries={max_entries}, "
                    f"size={max_size}, block={block_size})."
                ),
            )

        graphic_type = COLOR_SCHEME_TO_GRAPHIC_TYPE.get(color_scheme)
        if graphic_type is None:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"dmsColorScheme={color_scheme} desconocido — no se "
                    f"puede elegir dmsGraphicType compatible."
                ),
            )

        ctx.record_step(
            "capabilities",
            operation="SNMP_GET",
            value_read={
                "dmsColorScheme": color_scheme,
                "dmsGraphicMaxEntries": max_entries,
                "dmsGraphicMaxSize_bytes": max_size,
                "dmsGraphicBlockSize_bytes": block_size,
                "sign_h_x_w": [sign_h, sign_w],
                "chosen_graphic_type": graphic_type,
            },
            success=True,
        )

        # --- Paso 2: parsear y convertir el BMP --------------------------
        try:
            bitmap_bytes, gh, gw = _bmp_to_ntcip_bitmap(bmp_path, graphic_type)
        except Exception as exc:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"Error parseando/convirtiendo BMP: {exc}",
                error=repr(exc),
            )

        ctx.record_step(
            "bmp_loaded",
            operation="LOCAL",
            value_read={
                "bmp_path": bmp_path,
                "dimensions_h_x_w": [gh, gw],
                "bitmap_size_bytes": len(bitmap_bytes),
                "blocks_required": (
                    (len(bitmap_bytes) + block_size - 1) // block_size
                ),
            },
            success=True,
        )

        # Validar tamaño + dimensiones contra capacidades del panel
        if len(bitmap_bytes) > max_size:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Bitmap ({len(bitmap_bytes)} bytes) excede "
                    f"dmsGraphicMaxSize ({max_size}). Reducir BMP o "
                    f"cambiar de panel."
                ),
            )
        if sign_h and gh > sign_h:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Altura del BMP ({gh}px) excede la del panel "
                    f"({sign_h}px)."
                ),
            )
        if sign_w and gw > sign_w:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=(
                    f"Ancho del BMP ({gw}px) excede el del panel "
                    f"({sign_w}px)."
                ),
            )

        # --- Paso 3: elegir slot ------------------------------------------
        configured_index = int(
            ctx.device_config.get(
                "poc_15b_graphic_index", self.default_graphic_index
            )
        )
        if configured_index > 0:
            graphic_index = configured_index
            status_at_index = await self._read_graphic_status(
                ctx, graphic_index
            )
            if status_at_index in (
                oids.GRAPHIC_STATUS_IN_USE,
                oids.GRAPHIC_STATUS_PERMANENT,
            ):
                return ScenarioResult(
                    scenario_id=self.id,
                    status=STATUS_FAIL,
                    summary=(
                        f"Slot {graphic_index} configurado está en estado "
                        f"{decoders.decode_graphic_status(status_at_index)} "
                        f"— no se puede sobrescribir."
                    ),
                )
        else:
            # Auto-pick: primer slot en notUsed desde `poc_15b_min_slot`
            # (default 1). Setear min_slot=2 para no usar nunca el slot 1.
            min_slot = int(ctx.device_config.get("poc_15b_min_slot", 1))
            graphic_index = await self._find_free_slot(
                ctx, max_entries, start=min_slot
            )
            if graphic_index is None:
                return ScenarioResult(
                    scenario_id=self.id,
                    status=STATUS_FAIL,
                    summary=(
                        f"No hay slots libres entre {min_slot}.."
                        f"{min(max_entries, 16)} para cargar el gráfico."
                    ),
                )

        ctx.record_step(
            "slot_chosen",
            operation="VERIFY",
            value_read={"graphic_index": graphic_index},
            success=True,
        )

        # --- Paso 4: ritual de carga -------------------------------------
        graphic_number = int(
            ctx.device_config.get(
                "poc_15b_graphic_number", self.default_graphic_number
            )
        )
        graphic_name = str(
            ctx.device_config.get(
                "poc_15b_graphic_name", self.default_graphic_name
            )
        )

        load_err = await self._load_graphic(
            ctx,
            graphic_index=graphic_index,
            graphic_number=graphic_number,
            graphic_name=graphic_name,
            graphic_type=graphic_type,
            height=gh,
            width=gw,
            bitmap_bytes=bitmap_bytes,
            block_size=block_size,
        )
        if load_err is not None:
            # Caso especial: si el PRIMER SET del ritual (modifyReq sobre
            # dmsGraphicStatus) es rechazado, el panel declara capacidades
            # de gráficos pero sus objetos son read-only — no se pueden
            # cargar gráficos vía SNMP. Es un comportamiento de firmware
            # documentable, no un fallo del toolkit → QUIRK_PROVIDER.
            if load_err.startswith("set_modifyReq:"):
                return ScenarioResult(
                    scenario_id=self.id,
                    status=STATUS_QUIRK,
                    summary=(
                        f"El panel declara gráficos (dmsColorScheme="
                        f"{color_scheme}, {max_entries} slots) pero rechaza "
                        f"la escritura del dmsGraphicTable ({load_err}). "
                        f"Los objetos de gráficos son read-only en este "
                        f"firmware."
                    ),
                    design_impact=(
                        "Carga de gráficos vía SNMP NO viable en este panel. "
                        "Los gráficos deben pre-cargarse con el tooling del "
                        "fabricante (Venus/DMP UI) o el caso de uso debe "
                        "excluirlos. El capability profile debe marcar "
                        "graphics como 'read-only' pese a dmsGraphicMaxEntries."
                    ),
                    error=load_err,
                )
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_FAIL,
                summary=f"Carga del gráfico falló: {load_err}",
                error=load_err,
            )

        # --- Paso 5: verificar CRC ---------------------------------------
        crc_oid = f"{oids.DMS_GRAPHIC_ID_COL}.{graphic_index}"
        status_oid = f"{oids.DMS_GRAPHIC_STATUS_COL}.{graphic_index}"
        final_vals, _ = await ctx.snmp.get_many([crc_oid, status_oid])
        crc_value = _safe_int(final_vals.get(crc_oid))
        final_status = _safe_int(final_vals.get(status_oid))

        ctx.record_step(
            "verify",
            operation="SNMP_GET",
            value_read={
                "dmsGraphicID": crc_value,
                "dmsGraphicStatus": decoders.decode_graphic_status(final_status),
            },
            success=(
                crc_value is not None
                and crc_value != 0
                and final_status == oids.GRAPHIC_STATUS_READY_FOR_USE
            ),
        )

        if final_status != oids.GRAPHIC_STATUS_READY_FOR_USE or not crc_value:
            return ScenarioResult(
                scenario_id=self.id,
                status=STATUS_PARTIAL,
                summary=(
                    f"Gráfico cargado pero estado final no es readyForUse "
                    f"(estado={final_status}, CRC={crc_value})."
                ),
                design_impact=(
                    "Panel acepta los SETs pero no validó el gráfico — "
                    "revisar formato/dimensiones contra firmware real."
                ),
            )

        # --- Paso 6 (opcional): activar mensaje [gN] ---------------------
        activate_visual = bool(
            ctx.device_config.get("poc_15b_activate", self.default_activate)
        )
        activated_summary = ""
        if activate_visual:
            activate_err = await self._activate_with_graphic(
                ctx,
                graphic_number=graphic_number,
                slot=int(
                    ctx.device_config.get(
                        "poc_15b_activate_slot", self.default_activate_slot
                    )
                ),
                priority=int(
                    ctx.device_config.get(
                        "poc_15b_activate_priority",
                        self.default_activate_priority,
                    )
                ),
            )
            if activate_err:
                activated_summary = (
                    f" Activación visual falló: {activate_err}."
                )
            else:
                activated_summary = " Activado en pantalla con [g{}].".format(
                    graphic_number
                )

        return ScenarioResult(
            scenario_id=self.id,
            status=STATUS_PASS,
            summary=(
                f"Gráfico {gw}x{gh}px cargado en slot {graphic_index} "
                f"(number={graphic_number}, CRC={crc_value}, "
                f"{len(bitmap_bytes)}B en "
                f"{(len(bitmap_bytes) + block_size - 1) // block_size} "
                f"blocks).{activated_summary}"
            ),
        )

    # ---------------------------------------------------------------- helpers

    async def _read_graphic_status(
        self, ctx: ScenarioContext, idx: int
    ) -> Optional[int]:
        oid = f"{oids.DMS_GRAPHIC_STATUS_COL}.{idx}"
        raw, _ = await ctx.snmp.get_one(oid)
        return _safe_int(raw)

    async def _find_free_slot(
        self, ctx: ScenarioContext, max_entries: int, *, start: int = 1
    ) -> Optional[int]:
        """Buscar el primer slot libre desde ``start`` hasta el 16.

        Un slot está libre si su ``dmsGraphicStatus`` es ``notUsed(1)`` o si
        la fila no existe todavía (``None`` / NoSuchInstance). Muchos agentes
        NTCIP no materializan las filas del ``dmsGraphicTable`` hasta que se
        escriben: una fila inexistente es escribible, no ocupada.
        """
        scanned: List[dict] = []
        for idx in range(max(1, start), min(max_entries, 16) + 1):
            status = await self._read_graphic_status(ctx, idx)
            scanned.append({"slot": idx, "status": status})
            if status in (oids.GRAPHIC_STATUS_NOT_USED, None):
                ctx.record_step(
                    "find_free_slot",
                    operation="VERIFY",
                    value_read={"chosen": idx, "scanned": scanned},
                    success=True,
                )
                return idx
        ctx.record_step(
            "find_free_slot",
            operation="VERIFY",
            value_read={"chosen": None, "scanned": scanned},
            success=False,
        )
        return None

    async def _load_graphic(
        self,
        ctx: ScenarioContext,
        *,
        graphic_index: int,
        graphic_number: int,
        graphic_name: str,
        graphic_type: int,
        height: int,
        width: int,
        bitmap_bytes: bytes,
        block_size: int,
    ) -> Optional[str]:
        """Ejecuta el state machine completo. Devuelve None si OK, msg si falla."""
        idx = graphic_index
        status_oid = f"{oids.DMS_GRAPHIC_STATUS_COL}.{idx}"
        number_oid = f"{oids.DMS_GRAPHIC_NUMBER_COL}.{idx}"
        name_oid = f"{oids.DMS_GRAPHIC_NAME_COL}.{idx}"
        height_oid = f"{oids.DMS_GRAPHIC_HEIGHT_COL}.{idx}"
        width_oid = f"{oids.DMS_GRAPHIC_WIDTH_COL}.{idx}"
        type_oid = f"{oids.DMS_GRAPHIC_TYPE_COL}.{idx}"
        trans_en_oid = f"{oids.DMS_GRAPHIC_TRANSPARENT_ENABLED_COL}.{idx}"

        # A — modifyReq → modifying
        _, err = await ctx.snmp.set_one(
            status_oid, Integer(oids.GRAPHIC_STATUS_MODIFY_REQ)
        )
        ctx.record_step(
            "load.set_modifyReq",
            operation="SNMP_SET",
            oid=status_oid,
            value_read=oids.GRAPHIC_STATUS_MODIFY_REQ,
            success=err is None,
            error=err,
        )
        if err is not None:
            return f"set_modifyReq:{err}"

        state, wait_err = await self._wait_status(
            ctx, status_oid, desired=oids.GRAPHIC_STATUS_MODIFYING
        )
        if wait_err is not None:
            return f"wait_modifying:{wait_err}"

        # B — metadata
        _, err = await ctx.snmp.set_many(
            [
                (number_oid, Integer(graphic_number)),
                (name_oid, OctetString(graphic_name.encode("utf-8"))),
                (height_oid, Integer(height)),
                (width_oid, Integer(width)),
                (type_oid, Integer(graphic_type)),
                (trans_en_oid, Integer(0)),  # transparent disabled
            ]
        )
        ctx.record_step(
            "load.set_metadata",
            operation="SNMP_SET",
            value_read={
                "number": graphic_number,
                "name": graphic_name,
                "height": height,
                "width": width,
                "type": graphic_type,
            },
            success=err is None,
            error=err,
        )
        if err is not None:
            return f"set_metadata:{err}"

        # C — escribir bitmap en blocks
        n_blocks = (len(bitmap_bytes) + block_size - 1) // block_size
        for blk in range(1, n_blocks + 1):
            offset = (blk - 1) * block_size
            chunk = bitmap_bytes[offset : offset + block_size]
            block_oid = f"{oids.DMS_GRAPHIC_BLOCK_BITMAP_COL}.{idx}.{blk}"
            _, err = await ctx.snmp.set_one(block_oid, OctetString(chunk))
            if err is not None:
                ctx.record_step(
                    f"load.set_block_{blk}",
                    operation="SNMP_SET",
                    oid=block_oid,
                    value_read={"len": len(chunk), "block": blk, "of": n_blocks},
                    success=False,
                    error=err,
                )
                return f"set_block_{blk}:{err}"
        ctx.record_step(
            "load.all_blocks_written",
            operation="SNMP_SET",
            value_read={"total_blocks": n_blocks, "total_bytes": len(bitmap_bytes)},
            success=True,
        )

        # D — readyForUseReq → calculatingID/readyForUse
        _, err = await ctx.snmp.set_one(
            status_oid, Integer(oids.GRAPHIC_STATUS_READY_FOR_USE_REQ)
        )
        ctx.record_step(
            "load.set_readyForUseReq",
            operation="SNMP_SET",
            oid=status_oid,
            value_read=oids.GRAPHIC_STATUS_READY_FOR_USE_REQ,
            success=err is None,
            error=err,
        )
        if err is not None:
            return f"set_readyForUseReq:{err}"

        # El panel pasa por calculatingID antes de readyForUse — esperamos
        # generoso porque computar CRC puede tardar.
        state, wait_err = await self._wait_status(
            ctx,
            status_oid,
            desired=oids.GRAPHIC_STATUS_READY_FOR_USE,
            timeout=15.0,
        )
        if wait_err is not None:
            return f"wait_readyForUse:{wait_err} (state={state})"
        return None

    async def _wait_status(
        self,
        ctx: ScenarioContext,
        oid: str,
        *,
        desired: int,
        timeout: float = 5.0,
        interval: float = 0.3,
    ) -> Tuple[Optional[int], Optional[str]]:
        """Poll del status hasta llegar a desired o estado terminal."""
        import asyncio

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        TERMINAL = {oids.GRAPHIC_STATUS_NOT_USED}  # otros estados terminales
        last: Optional[int] = None
        while True:
            raw, err = await ctx.snmp.get_one(oid)
            if err is not None:
                return last, err
            last = _safe_int(raw)
            if last == desired:
                return last, None
            if last in TERMINAL and last != desired:
                return last, f"TERMINAL_STATE_{last}"
            if loop.time() >= deadline:
                return last, "TIMEOUT_WAITING_STATE"
            await asyncio.sleep(interval)

    async def _activate_with_graphic(
        self,
        ctx: ScenarioContext,
        *,
        graphic_number: int,
        slot: int,
        priority: int = 255,
    ) -> Optional[str]:
        """Carga un MULTI '[gN]' en un slot y lo activa con prioridad alta.

        ``priority`` se usa tanto como ``run_time_priority`` del mensaje
        como ``activate_priority`` de la activación, para que el visual pueda
        pisar el mensaje que el panel esté mostrando.
        """
        multi = f"[g{graphic_number}]"
        loaded, load_err = await _activation.load_message_into_slot(
            ctx,
            memory_type=oids.MEM_TYPE_CHANGEABLE,
            message_number=slot,
            multi=multi,
            run_time_priority=priority,
        )
        if loaded is None:
            return f"load_msg:{load_err}"
        err_text, err_value = await _activation.activate_message(
            ctx, loaded=loaded, activate_priority=priority
        )
        if err_value != 2:
            return f"activate:{err_text}"
        return None


# ---------------------------------------------------------------------------
# BMP → bitmap NTCIP
# ---------------------------------------------------------------------------


def _bmp_to_ntcip_bitmap(
    path: str, graphic_type: int
) -> Tuple[bytes, int, int]:
    """Convierte un BMP a la representación binaria NTCIP del tipo elegido.

    Devuelve ``(bitmap_bytes, height, width)``.

    - ``color24bit``: 3 bytes por pixel en orden B, G, R (NTCIP §5.12.7).
    - ``monochrome8bit``: 1 byte por pixel, valor = luminancia 0-255.
    - ``monochrome1bit``: 1 bit por pixel, MSB-first, row-major; threshold
      luminancia > 127 = ON.
    """
    from PIL import Image

    img = Image.open(path)
    img = img.convert("RGB")  # normaliza independientemente del modo origen
    w, h = img.size
    pixels = list(img.getdata())  # lista de (r, g, b) row-major top-to-bottom

    if graphic_type == oids.GRAPHIC_TYPE_COLOR_24BIT:
        # NTCIP §5.12.7: "first byte shall be blue, second green, third red"
        out = bytearray(w * h * 3)
        for i, (r, g, b) in enumerate(pixels):
            out[i * 3] = b
            out[i * 3 + 1] = g
            out[i * 3 + 2] = r
        return bytes(out), h, w

    if graphic_type == oids.GRAPHIC_TYPE_MONOCHROME_8BIT:
        out = bytearray(w * h)
        for i, (r, g, b) in enumerate(pixels):
            # Luma BT.601 aproximada
            out[i] = (299 * r + 587 * g + 114 * b) // 1000
        return bytes(out), h, w

    if graphic_type == oids.GRAPHIC_TYPE_MONOCHROME_1BIT:
        # NTCIP §5.12.7: MSB del primer byte = pixel arriba-izquierda
        total_bits = w * h
        out = bytearray((total_bits + 7) // 8)
        for i, (r, g, b) in enumerate(pixels):
            luma = (299 * r + 587 * g + 114 * b) // 1000
            if luma > 127:
                byte_i = i // 8
                bit_i = 7 - (i % 8)
                out[byte_i] |= 1 << bit_i
        return bytes(out), h, w

    raise ValueError(f"dmsGraphicType={graphic_type} no soportado por el converter")


def _safe_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None
