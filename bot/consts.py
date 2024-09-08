from enum import Enum

from sc2.ids.unit_typeid import UnitTypeId as UnitID

COMMON_UNIT_IGNORE_TYPES: set[UnitID] = {UnitID.EGG, UnitID.LARVA, UnitID.BROODLING}


class RequestType(str, Enum):
    GET_ARMY_COMP = "GET_ARMY_COMP"
    GET_ENEMY_PROXIES = "GET_ENEMY_PROXIES"
    GET_ENEMY_RUSHED = "GET_ENEMY_RUSHED"
