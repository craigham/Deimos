from enum import Enum

from ares import UnitRole
from sc2.ids.unit_typeid import UnitTypeId as UnitID

COMMON_UNIT_IGNORE_TYPES: set[UnitID] = {UnitID.EGG, UnitID.LARVA}

# typical roles that managers will steal units from
STEAL_FROM_ROLES: set[UnitRole] = {UnitRole.ATTACKING, UnitRole.DEFENDING}


class RequestType(str, Enum):
    GET_ADEPT_TO_PHASE = "GET_ADEPT_TO_PHASE"
    GET_ARMY_COMP = "GET_ARMY_COMP"
    GET_ENEMY_EARLY_DOUBLE_GAS = "GET_ENEMY_EARLY_DOUBLE_GAS"
    GET_ENEMY_EARLY_ROACH_WARREN = "GET_ENEMY_EARLY_ROACH_WARREN"
    GET_ENEMY_PROXIES = "GET_ENEMY_PROXIES"
    GET_ENEMY_RUSHED = "GET_ENEMY_RUSHED"


STATIC_DEFENCE: set[UnitID] = {
    UnitID.SPINECRAWLER,
    UnitID.SPORECRAWLER,
    UnitID.PHOTONCANNON,
    UnitID.MISSILETURRET,
    UnitID.PLANETARYFORTRESS,
}
