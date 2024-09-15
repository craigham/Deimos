from dataclasses import dataclass
from itertools import cycle
from typing import TYPE_CHECKING

import numpy as np
from ares import ManagerMediator
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    KeepUnitSafe,
    ShootTargetInRange,
    UseAbility,
)
from sc2.ids.ability_id import AbilityId
from sc2.units import Units
from src.ares.consts import UnitTreeQueryType

from bot.combat.base_unit import BaseUnit

if TYPE_CHECKING:
    from ares import AresBot


@dataclass
class MapControlAdepts(BaseUnit):
    """Execute behavior for map control adepts.

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
    current_shade_target = None

    def __post_init__(self) -> None:
        self.shade_target_generator = None
        self._create_shade_target_generator()
        self.current_shade_target = next(self.shade_target_generator)

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
        grid : np.ndarray
        """

        if self.ai.is_visible(self.current_shade_target):
            self.current_shade_target = next(self.shade_target_generator)

        grid: np.ndarray = kwargs["grid"]

        everything_near_adepts: dict[int, Units] = self.mediator.get_units_in_range(
            start_points=units,
            distances=12.0,
            query_tree=UnitTreeQueryType.EnemyGround,
            return_as_dict=True,
        )

        for unit in units:
            unit_tag: int = unit.tag
            close_enemy: Units = everything_near_adepts[unit_tag]

            maneuver: CombatManeuver = CombatManeuver()
            maneuver.add(
                UseAbility(
                    AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT,
                    unit,
                    self.current_shade_target,
                )
            )
            maneuver.add(ShootTargetInRange(unit=unit, targets=close_enemy))
            maneuver.add(KeepUnitSafe(unit, grid))
            maneuver.add(AMove(unit, self.mediator.get_enemy_nat))

            self.ai.register_behavior(maneuver)

    def _create_shade_target_generator(self):
        spots = [
            self.ai.enemy_start_locations[0],
            self.mediator.get_enemy_expansions[1][0],
            self.mediator.get_enemy_expansions[2][0],
            self.mediator.get_enemy_expansions[3][0],
        ]

        self.shade_target_generator = cycle(spots)
