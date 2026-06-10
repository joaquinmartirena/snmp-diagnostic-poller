"""Catálogo de OIDs del VMS NTCIP 1203 v3.

Reúne en un único archivo lo que en el legacy estaba repartido entre
`shared/oid_providers/base.py` (system group + NTCIP 1201) y
`shared/oid_providers/ntcip1203_v3.py` (dms node).

OID values verificados contra:
- RFC 3418 (SNMPv2-MIB system group).
- NTCIP 1201 v03.15 (Global Object Definitions).
- NTCIP 1203 v03.05 (DMS).

INVARIANTE: ningún OID se hardcodea fuera de este módulo dentro del paquete.
Los decoders, el adapter y los escenarios resuelven OIDs por nombre acá.

Los escalares de capacidad (Fase 5, POC-VMS-03) están agrupados al final por
sub-módulo NTCIP: dmsSignCfg, vmsCfg, dmsMessage, dmsIllum, dmsGraphic,
schedule (NTCIP 1201). Los valores se ajustan contra firmware real en
POC-VMS-02 — si el panel devuelve ``NoSuchObject`` para alguno, el scenario
lo registra como ``unsupported`` sin fallar el resto.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# SNMPv2-MIB system group (RFC 3418) — 1.3.6.1.2.1.1
# ---------------------------------------------------------------------------
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"

# ---------------------------------------------------------------------------
# NTCIP 1201 Global Object Definitions — enterprise 1206.4.2.6
# ---------------------------------------------------------------------------
GLOBAL_BASE = "1.3.6.1.4.1.1206.4.2.6"

GLOBAL_SET_ID_PARAMETER = "1.3.6.1.4.1.1206.4.2.6.1.1.0"
GLOBAL_MAX_MODULES = "1.3.6.1.4.1.1206.4.2.6.1.2.0"
GLOBAL_MODULE_TABLE = "1.3.6.1.4.1.1206.4.2.6.1.3"
CONTROLLER_BASE_STANDARDS = "1.3.6.1.4.1.1206.4.2.6.1.4.0"

GLOBAL_TIME = "1.3.6.1.4.1.1206.4.2.6.3.1.0"
# globalDaylightSaving — NTCIP 1201 timeBase 2 (algunos firmwares usan otro
# layout para "hora local"; lo dejamos disponible para POC-11).
GLOBAL_DAYLIGHT_SAVING = "1.3.6.1.4.1.1206.4.2.6.3.2.0"

MODULE_DEVICE_NODE_COL = "1.3.6.1.4.1.1206.4.2.6.1.3.1.2"
MODULE_MAKE_COL = "1.3.6.1.4.1.1206.4.2.6.1.3.1.3"
MODULE_MODEL_COL = "1.3.6.1.4.1.1206.4.2.6.1.3.1.4"
MODULE_VERSION_COL = "1.3.6.1.4.1.1206.4.2.6.1.3.1.5"

# NTCIP 1201 Schedule (globalConfiguration.timeBase) — 1.3.6.1.4.1.1206.4.2.6.3
SCHED_MAX_TIME_BASE_SCHEDULE_ENTRIES = "1.3.6.1.4.1.1206.4.2.6.3.3.1.0"
SCHED_MAX_DAY_PLANS = "1.3.6.1.4.1.1206.4.2.6.3.3.3.0"
SCHED_MAX_DAY_PLAN_EVENTS = "1.3.6.1.4.1.1206.4.2.6.3.3.4.0"

# ---------------------------------------------------------------------------
# NTCIP 1203 v3 DMS — 1.3.6.1.4.1.1206.4.2.3
# ---------------------------------------------------------------------------
DMS_BASE = "1.3.6.1.4.1.1206.4.2.3"

# dmsSignCfg (dms 1) — configuración del panel ----------------------------
DMS_SIGN_ACCESS = "1.3.6.1.4.1.1206.4.2.3.1.1.0"
DMS_SIGN_TYPE = "1.3.6.1.4.1.1206.4.2.3.1.2.0"
DMS_SIGN_HEIGHT_MM = "1.3.6.1.4.1.1206.4.2.3.1.3.0"
DMS_SIGN_WIDTH_MM = "1.3.6.1.4.1.1206.4.2.3.1.4.0"
DMS_HORIZONTAL_BORDER = "1.3.6.1.4.1.1206.4.2.3.1.5.0"
DMS_VERTICAL_BORDER = "1.3.6.1.4.1.1206.4.2.3.1.6.0"
DMS_LEGEND = "1.3.6.1.4.1.1206.4.2.3.1.7.0"
DMS_BEACON_TYPE = "1.3.6.1.4.1.1206.4.2.3.1.8.0"
DMS_SIGN_TECHNOLOGY = "1.3.6.1.4.1.1206.4.2.3.1.9.0"

# vmsCfg (dms 2) — dimensiones de píxel del display
VMS_CHARACTER_HEIGHT_PIXELS = "1.3.6.1.4.1.1206.4.2.3.2.1.0"
VMS_CHARACTER_WIDTH_PIXELS = "1.3.6.1.4.1.1206.4.2.3.2.2.0"
VMS_SIGN_HEIGHT_PIXELS = "1.3.6.1.4.1.1206.4.2.3.2.3.0"
VMS_SIGN_WIDTH_PIXELS = "1.3.6.1.4.1.1206.4.2.3.2.4.0"
VMS_HORIZONTAL_PITCH = "1.3.6.1.4.1.1206.4.2.3.2.5.0"
VMS_VERTICAL_PITCH = "1.3.6.1.4.1.1206.4.2.3.2.6.0"
VMS_MONOCHROME_COLOR = "1.3.6.1.4.1.1206.4.2.3.2.7.0"

# fontDefinition (dms 3) — escalares de la tabla de fuentes
NUM_FONTS = "1.3.6.1.4.1.1206.4.2.3.3.1.0"
MAX_FONT_CHARACTERS = "1.3.6.1.4.1.1206.4.2.3.3.3.0"
FONT_MAX_CHARACTER_SIZE = "1.3.6.1.4.1.1206.4.2.3.3.5.0"

# multiCfg (dms 4) — defaults MULTI + capacidades de color/MULTI
DEFAULT_FONT = "1.3.6.1.4.1.1206.4.2.3.4.5.0"
DMS_COLOR_SCHEME = "1.3.6.1.4.1.1206.4.2.3.4.11.0"
DMS_SUPPORTED_MULTI_TAGS = "1.3.6.1.4.1.1206.4.2.3.4.14.0"
DMS_MAX_NUMBER_PAGES = "1.3.6.1.4.1.1206.4.2.3.4.15.0"
DMS_MAX_MULTI_STRING_LENGTH = "1.3.6.1.4.1.1206.4.2.3.4.16.0"

# dmsMessage (dms 5) — capacidades de mensajes
DMS_NUM_PERMANENT_MSG = "1.3.6.1.4.1.1206.4.2.3.5.1.0"
DMS_NUM_CHANGEABLE_MSG = "1.3.6.1.4.1.1206.4.2.3.5.2.0"
DMS_MAX_CHANGEABLE_MSG = "1.3.6.1.4.1.1206.4.2.3.5.3.0"
DMS_FREE_CHANGEABLE_MEMORY = "1.3.6.1.4.1.1206.4.2.3.5.4.0"
DMS_NUM_VOLATILE_MSG = "1.3.6.1.4.1.1206.4.2.3.5.5.0"
DMS_MAX_VOLATILE_MSG = "1.3.6.1.4.1.1206.4.2.3.5.6.0"
DMS_FREE_VOLATILE_MEMORY = "1.3.6.1.4.1.1206.4.2.3.5.7.0"

# dmsSchedule (dms 8) — scheduling (NTCIP 1203)
NUM_ACTION_TABLE_ENTRIES = "1.3.6.1.4.1.1206.4.2.3.8.1.0"
# dmsActionTable columns (8.2.1.x)
DMS_ACTION_INDEX_COL = "1.3.6.1.4.1.1206.4.2.3.8.2.1.1"
DMS_ACTION_MSG_CODE_COL = "1.3.6.1.4.1.1206.4.2.3.8.2.1.2"

# signControl group (dms 6)
CTRL_MODE = "1.3.6.1.4.1.1206.4.2.3.6.1.0"  # dmsControlMode
DMS_SW_RESET = "1.3.6.1.4.1.1206.4.2.3.6.2.0"  # dmsSWReset
DMS_ACTIVATE_MESSAGE = "1.3.6.1.4.1.1206.4.2.3.6.3.0"  # dmsActivateMessage (write)
DMS_MESSAGE_TIME_REMAINING = "1.3.6.1.4.1.1206.4.2.3.6.4.0"
MSG_SRC = "1.3.6.1.4.1.1206.4.2.3.6.5.0"  # dmsMsgTableSource
SRC_MODE = "1.3.6.1.4.1.1206.4.2.3.6.7.0"  # dmsMsgSourceMode
DMS_ACTIVATE_MSG_ERROR = "1.3.6.1.4.1.1206.4.2.3.6.17.0"  # signControl 17
DMS_MULTI_SYNTAX_ERROR = "1.3.6.1.4.1.1206.4.2.3.6.18.0"  # signControl 18
DMS_MULTI_SYNTAX_ERROR_POSITION = "1.3.6.1.4.1.1206.4.2.3.6.19.0"  # signControl 19
DMS_ACTIVATE_ERROR_MSG_CODE = "1.3.6.1.4.1.1206.4.2.3.6.24.0"  # signControl 24

# dmsMessageEntry columns (dms 5.8.1.x) — indexar por memoryType.messageNumber
DMS_MSG_MEMORY_TYPE_COL = "1.3.6.1.4.1.1206.4.2.3.5.8.1.1"
DMS_MSG_NUMBER_COL = "1.3.6.1.4.1.1206.4.2.3.5.8.1.2"
DMS_MSG_MULTI_STRING_COL = "1.3.6.1.4.1.1206.4.2.3.5.8.1.3"
DMS_MSG_OWNER_COL = "1.3.6.1.4.1.1206.4.2.3.5.8.1.4"
DMS_MSG_CRC_COL = "1.3.6.1.4.1.1206.4.2.3.5.8.1.5"
DMS_MSG_BEACON_COL = "1.3.6.1.4.1.1206.4.2.3.5.8.1.6"
DMS_MSG_PIXEL_SERVICE_COL = "1.3.6.1.4.1.1206.4.2.3.5.8.1.7"
DMS_MSG_RUN_TIME_PRIORITY_COL = "1.3.6.1.4.1.1206.4.2.3.5.8.1.8"
DMS_MSG_STATUS_COL = "1.3.6.1.4.1.1206.4.2.3.5.8.1.9"

# Memory type enums (dmsMessageMemoryType)
MEM_TYPE_PERMANENT = 2
MEM_TYPE_CHANGEABLE = 3
MEM_TYPE_VOLATILE = 4
MEM_TYPE_CURRENT_BUFFER = 5
MEM_TYPE_SCHEDULE = 6
MEM_TYPE_BLANK = 7

# dmsMessageStatus state machine (5.8.1.9)
MSG_STATUS_NOT_USED = 1
MSG_STATUS_MODIFYING = 2
MSG_STATUS_VALIDATING = 3
MSG_STATUS_VALID = 4
MSG_STATUS_ERROR = 5
MSG_STATUS_MODIFY_REQ = 6
MSG_STATUS_VALIDATE_REQ = 7
MSG_STATUS_NOT_USED_REQ = 8

# illum (dms 7) — brillo
DMS_ILLUM_CONTROL = "1.3.6.1.4.1.1206.4.2.3.7.1.0"
DMS_ILLUM_MAX_PHOTOCELL_LEVEL = "1.3.6.1.4.1.1206.4.2.3.7.2.0"
DMS_ILLUM_PHOTOCELL_LEVEL_STATUS = "1.3.6.1.4.1.1206.4.2.3.7.3.0"
DMS_ILLUM_NUM_LEVELS = "1.3.6.1.4.1.1206.4.2.3.7.4.0"
DMS_ILLUM_BRIGHT_LEVEL_STATUS = "1.3.6.1.4.1.1206.4.2.3.7.5.0"
DMS_ILLUM_MAN_LEVEL = "1.3.6.1.4.1.1206.4.2.3.7.6.0"

# statError group (dms 9)
SHORT_ERR = "1.3.6.1.4.1.1206.4.2.3.9.7.1.0"  # shortErrorStatus

# graphicDefinition (dms 10) — capacidades de gráficos
DMS_GRAPHIC_MAX_ENTRIES = "1.3.6.1.4.1.1206.4.2.3.10.1.0"
DMS_NUM_GRAPHICS = "1.3.6.1.4.1.1206.4.2.3.10.2.0"
DMS_GRAPHIC_MAX_SIZE = "1.3.6.1.4.1.1206.4.2.3.10.3.0"
AVAILABLE_GRAPHIC_MEMORY = "1.3.6.1.4.1.1206.4.2.3.10.4.0"
DMS_GRAPHIC_BLOCK_SIZE = "1.3.6.1.4.1.1206.4.2.3.10.5.0"

# dmsGraphicEntry columns — indexados por dmsGraphicIndex.
# OJO: la cadena real es dmsGraphicTable(.6).dmsGraphicEntry(.1).columna,
# o sea 10.6.1.<col>. El PDF anota el OID como "10.6.<col>" (omite el .1
# del entry) — esa anotación NO es el OID accesible. Verificado contra
# firmware real (Chainzone): 10.6.1.10.<idx> responde, 10.6.10.<idx> da
# NoSuchObject.
DMS_GRAPHIC_INDEX_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.1"
DMS_GRAPHIC_NUMBER_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.2"
DMS_GRAPHIC_NAME_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.3"
DMS_GRAPHIC_HEIGHT_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.4"
DMS_GRAPHIC_WIDTH_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.5"
DMS_GRAPHIC_TYPE_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.6"
DMS_GRAPHIC_ID_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.7"
DMS_GRAPHIC_TRANSPARENT_ENABLED_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.8"
DMS_GRAPHIC_TRANSPARENT_COLOR_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.9"
DMS_GRAPHIC_STATUS_COL = "1.3.6.1.4.1.1206.4.2.3.10.6.1.10"

# dmsGraphicBitmapTable (10.7) — indexado por dmsGraphicIndex.dmsGraphicBlockNumber
DMS_GRAPHIC_BLOCK_BITMAP_COL = "1.3.6.1.4.1.1206.4.2.3.10.7.1.3"

# Enums dmsGraphicType (col 10.6.6)
GRAPHIC_TYPE_MONOCHROME_1BIT = 1
GRAPHIC_TYPE_MONOCHROME_8BIT = 2
GRAPHIC_TYPE_COLOR_CLASSIC = 3
GRAPHIC_TYPE_COLOR_24BIT = 4

# Enums dmsGraphicStatus (col 10.6.10) — state machine NTCIP 1203 §4.3.2
GRAPHIC_STATUS_NOT_USED = 1
GRAPHIC_STATUS_MODIFYING = 2
GRAPHIC_STATUS_CALCULATING_ID = 3
GRAPHIC_STATUS_READY_FOR_USE = 4
GRAPHIC_STATUS_IN_USE = 5
GRAPHIC_STATUS_PERMANENT = 6
GRAPHIC_STATUS_MODIFY_REQ = 7
GRAPHIC_STATUS_READY_FOR_USE_REQ = 8
GRAPHIC_STATUS_NOT_USED_REQ = 9

# Enums dmsColorScheme (4.11) — duplicados acá como ints para usar sin decoder
COLOR_SCHEME_MONOCHROME_1BIT = 1
COLOR_SCHEME_MONOCHROME_8BIT = 2
COLOR_SCHEME_COLOR_CLASSIC = 3
COLOR_SCHEME_COLOR_24BIT = 4

# dmsMessageMultiString column (dms 5.8.1.3); indexed by
# dmsMessageMemoryType . dmsMessageNumber.
MULTI_BASE = "1.3.6.1.4.1.1206.4.2.3.5.8.1.3"


# ---------------------------------------------------------------------------
# Conjuntos lógicos
# ---------------------------------------------------------------------------


def system_oids() -> list[str]:
    """Escalares estándar del system group, útiles para identificar el panel."""
    return [SYS_DESCR, SYS_OBJECT_ID, SYS_UPTIME, SYS_NAME]


def identity_oids() -> list[str]:
    """Escalares NTCIP 1201 útiles para fingerprint del controlador."""
    return [GLOBAL_SET_ID_PARAMETER, CONTROLLER_BASE_STANDARDS]


def required_oids() -> list[str]:
    """Escalares polleados en cada ciclo del modo monitor."""
    return [CTRL_MODE, SRC_MODE, MSG_SRC, SHORT_ERR]


def multi_oid(memory_type: int, message_number: int) -> str:
    """OID completo del MULTI string del mensaje activo."""
    return f"{MULTI_BASE}.{memory_type}.{message_number}"


# ---------------------------------------------------------------------------
# Conjuntos de capacidad — usados por POC-VMS-03
# ---------------------------------------------------------------------------

#: OIDs críticos. Si alguno falla en POC-VMS-03 el scenario es FAIL — sin
#: estas dimensiones / capacidades de memoria no se puede construir un
#: capability profile usable.
CAPABILITY_CRITICAL = {
    "vmsSignHeightPixels": VMS_SIGN_HEIGHT_PIXELS,
    "vmsSignWidthPixels": VMS_SIGN_WIDTH_PIXELS,
    "dmsSignHeight": DMS_SIGN_HEIGHT_MM,
    "dmsSignWidth": DMS_SIGN_WIDTH_MM,
    "dmsMaxChangeableMsg": DMS_MAX_CHANGEABLE_MSG,
    "dmsMaxNumberPages": DMS_MAX_NUMBER_PAGES,
    "dmsMaxMultiStringLength": DMS_MAX_MULTI_STRING_LENGTH,
}

#: OIDs opcionales. NoSuchObject → registramos como ``unsupported`` y seguimos.
CAPABILITY_OPTIONAL = {
    # bloque 1 — dimensiones físicas (mm + pitch)
    "vmsCharacterHeightPixels": VMS_CHARACTER_HEIGHT_PIXELS,
    "vmsCharacterWidthPixels": VMS_CHARACTER_WIDTH_PIXELS,
    "vmsHorizontalPitch": VMS_HORIZONTAL_PITCH,
    "vmsVerticalPitch": VMS_VERTICAL_PITCH,
    "dmsHorizontalBorder": DMS_HORIZONTAL_BORDER,
    "dmsVerticalBorder": DMS_VERTICAL_BORDER,
    "dmsSignType": DMS_SIGN_TYPE,
    "dmsSignTechnology": DMS_SIGN_TECHNOLOGY,
    # bloque 2 — color
    "dmsColorScheme": DMS_COLOR_SCHEME,
    "monochromeColor": VMS_MONOCHROME_COLOR,
    # bloque 3 — memoria (volatile)
    "dmsMaxVolatileMsg": DMS_MAX_VOLATILE_MSG,
    "dmsFreeChangeableMemory": DMS_FREE_CHANGEABLE_MEMORY,
    "dmsFreeVolatileMemory": DMS_FREE_VOLATILE_MEMORY,
    # bloque 4 — fuentes (solo escalares; tabla queda para bloque posterior)
    "numFonts": NUM_FONTS,
    "maxFontCharacters": MAX_FONT_CHARACTERS,
    "fontMaxCharacterSize": FONT_MAX_CHARACTER_SIZE,
    "defaultFont": DEFAULT_FONT,
    # bloque 5 — gráficos (solo escalares)
    "dmsGraphicMaxEntries": DMS_GRAPHIC_MAX_ENTRIES,
    "dmsGraphicMaxSize": DMS_GRAPHIC_MAX_SIZE,
    "dmsGraphicBlockSize": DMS_GRAPHIC_BLOCK_SIZE,
    "availableGraphicMemory": AVAILABLE_GRAPHIC_MEMORY,
    # bloque 6 — brillo
    "dmsIllumNumLevels": DMS_ILLUM_NUM_LEVELS,
    "dmsIllumControl": DMS_ILLUM_CONTROL,
    "dmsIllumManLevel": DMS_ILLUM_MAN_LEVEL,
    # bloque 7 — scheduler (NTCIP 1201 timeBase + NTCIP 1203 dmsSchedule)
    "maxTimeBaseScheduleEntries": SCHED_MAX_TIME_BASE_SCHEDULE_ENTRIES,
    "maxDayPlans": SCHED_MAX_DAY_PLANS,
    "maxDayPlanEvents": SCHED_MAX_DAY_PLAN_EVENTS,
    "numActionTableEntries": NUM_ACTION_TABLE_ENTRIES,
    # bloque 8 — MULTI tags
    "dmsSupportedMultiTags": DMS_SUPPORTED_MULTI_TAGS,
}


def capability_scalar_oids() -> list[str]:
    """Lista plana de OIDs escalares leídos por POC-VMS-03 (críticos + opcionales)."""
    return list(CAPABILITY_CRITICAL.values()) + list(CAPABILITY_OPTIONAL.values())


#: OIDs simbólicos principales — usados por POC-VMS-02 para verificar
#: disponibilidad. Mezcla system + NTCIP 1201 + signControl + statError.
NAMED_PRINCIPAL_OIDS = {
    "sysDescr": SYS_DESCR,
    "sysObjectID": SYS_OBJECT_ID,
    "sysUpTime": SYS_UPTIME,
    "sysName": SYS_NAME,
    "globalTime": GLOBAL_TIME,
    "dmsControlMode": CTRL_MODE,
    "dmsMessageSourceMode": SRC_MODE,
    "dmsMsgTableSource": MSG_SRC,
    "shortErrorStatus": SHORT_ERR,
    "dmsSupportedMultiTags": DMS_SUPPORTED_MULTI_TAGS,
    "dmsMaxChangeableMsg": DMS_MAX_CHANGEABLE_MSG,
}

#: Subconjunto crítico de NAMED_PRINCIPAL_OIDS. Sin éstos POC-VMS-02 falla;
#: el monitor depende de signControl + statError.
NAMED_PRINCIPAL_CRITICAL = {
    "sysDescr": SYS_DESCR,
    "sysUpTime": SYS_UPTIME,
    "dmsControlMode": CTRL_MODE,
    "dmsMessageSourceMode": SRC_MODE,
    "dmsMsgTableSource": MSG_SRC,
    "shortErrorStatus": SHORT_ERR,
}


__all__ = [
    # System group
    "SYS_DESCR",
    "SYS_OBJECT_ID",
    "SYS_UPTIME",
    "SYS_CONTACT",
    "SYS_NAME",
    "SYS_LOCATION",
    # NTCIP 1201
    "GLOBAL_BASE",
    "GLOBAL_SET_ID_PARAMETER",
    "GLOBAL_MAX_MODULES",
    "GLOBAL_MODULE_TABLE",
    "CONTROLLER_BASE_STANDARDS",
    "GLOBAL_TIME",
    "MODULE_DEVICE_NODE_COL",
    "MODULE_MAKE_COL",
    "MODULE_MODEL_COL",
    "MODULE_VERSION_COL",
    "SCHED_MAX_TIME_BASE_SCHEDULE_ENTRIES",
    "SCHED_MAX_DAY_PLANS",
    "SCHED_MAX_DAY_PLAN_EVENTS",
    "NUM_ACTION_TABLE_ENTRIES",
    # NTCIP 1203 base + monitor
    "DMS_BASE",
    "CTRL_MODE",
    "MSG_SRC",
    "SRC_MODE",
    "SHORT_ERR",
    "MULTI_BASE",
    # dmsSignCfg
    "DMS_SIGN_ACCESS",
    "DMS_SIGN_TYPE",
    "DMS_SIGN_HEIGHT_MM",
    "DMS_SIGN_WIDTH_MM",
    "DMS_HORIZONTAL_BORDER",
    "DMS_VERTICAL_BORDER",
    "DMS_LEGEND",
    "DMS_BEACON_TYPE",
    "DMS_SIGN_TECHNOLOGY",
    # vmsCfg
    "VMS_SIGN_HEIGHT_PIXELS",
    "VMS_SIGN_WIDTH_PIXELS",
    "VMS_HORIZONTAL_PITCH",
    "VMS_VERTICAL_PITCH",
    "VMS_CHARACTER_HEIGHT_PIXELS",
    "VMS_CHARACTER_WIDTH_PIXELS",
    "VMS_MONOCHROME_COLOR",
    # fontDefinition (escalares)
    "NUM_FONTS",
    "MAX_FONT_CHARACTERS",
    "FONT_MAX_CHARACTER_SIZE",
    # multiCfg (defaults + capacidades MULTI/color)
    "DEFAULT_FONT",
    "DMS_COLOR_SCHEME",
    "DMS_SUPPORTED_MULTI_TAGS",
    "DMS_MAX_NUMBER_PAGES",
    "DMS_MAX_MULTI_STRING_LENGTH",
    # dmsMessage
    "DMS_NUM_PERMANENT_MSG",
    "DMS_NUM_CHANGEABLE_MSG",
    "DMS_MAX_CHANGEABLE_MSG",
    "DMS_FREE_CHANGEABLE_MEMORY",
    "DMS_NUM_VOLATILE_MSG",
    "DMS_MAX_VOLATILE_MSG",
    "DMS_FREE_VOLATILE_MEMORY",
    # dmsSchedule
    "NUM_ACTION_TABLE_ENTRIES",
    # dmsIllum
    "DMS_ILLUM_CONTROL",
    "DMS_ILLUM_MAX_PHOTOCELL_LEVEL",
    "DMS_ILLUM_PHOTOCELL_LEVEL_STATUS",
    "DMS_ILLUM_NUM_LEVELS",
    "DMS_ILLUM_MAN_LEVEL",
    "DMS_ILLUM_BRIGHT_LEVEL_STATUS",
    # graphicDefinition
    "DMS_GRAPHIC_MAX_ENTRIES",
    "DMS_NUM_GRAPHICS",
    "DMS_GRAPHIC_MAX_SIZE",
    "AVAILABLE_GRAPHIC_MEMORY",
    "DMS_GRAPHIC_BLOCK_SIZE",
    # Helpers
    "system_oids",
    "identity_oids",
    "required_oids",
    "multi_oid",
    "capability_scalar_oids",
    "CAPABILITY_CRITICAL",
    "CAPABILITY_OPTIONAL",
    "NAMED_PRINCIPAL_OIDS",
    "NAMED_PRINCIPAL_CRITICAL",
]
