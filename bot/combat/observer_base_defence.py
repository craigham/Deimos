from dataclasses import dataclass
from itertools import cycle
from typing import TYPE_CHECKING

import numpy as np
from ares import ManagerMediator
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import AMove, KeepUnitSafe, UseAbility
from map_analyzer import MapData
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from src.ares.consts import UnitTreeQueryType

from bot.combat.base_combat import BaseCombat
from bot.consts import COMMON_UNIT_IGNORE_TYPES
from cython_extensions import (
    cy_attack_ready,
    cy_closest_to,
    cy_distance_to,
    cy_distance_to_squared,
    cy_pick_enemy_target,
)

if TYPE_CHECKING:
    from ares import AresBot


@dataclass
class ObserverBaseDefence(BaseCombat):
    """Execute behavior for map control voidrays.

    Parameters
    ----------
    ai : AresBot
        Bot object that will be running the game
    config : Dict[Any, Any]
        Dictionary with the data from the configuration file
    mediator : ManagerMediator
        Used for getting information from managers in Ares.
    """

    ai: "AresBot"
    config: dict
    mediator: ManagerMediator

    def execute(self, units: Units, **kwargs) -> None:
        """Actually execute defensive void control.

        Parameters
        ----------
        units : Units
            The voids we want to control.
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        move_to : Point2
        """

        enemy_cloak: Units = kwargs["enemy_cloak"]
        move_to: Point2 = kwargs["move_to"]
        avoidance_grid: np.ndarray = self.mediator.get_air_avoidance_grid
        grid: np.ndarray = self.mediator.get_air_grid

        for unit in units:
            maneuver: CombatManeuver = CombatManeuver()
            maneuver.add(KeepUnitSafe(unit, avoidance_grid))
            maneuver.add(KeepUnitSafe(unit, grid))
            close_cloak: list[Unit] = [
                u
                for u in enemy_cloak
                if cy_distance_to_squared(u.position, unit.position) < 300.0
            ]

            if close_cloak:
                target: Unit = cy_closest_to(unit.position, close_cloak)
                maneuver.add(AMove(unit, target))
            else:
                maneuver.add(AMove(unit, move_to))

            self.ai.register_behavior(maneuver)
