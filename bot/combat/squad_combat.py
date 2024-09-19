from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    KeepUnitSafe,
    PathUnitToTarget,
    ShootTargetInRange,
    StutterUnitBack,
)
from ares.consts import ALL_STRUCTURES
from ares.managers.manager_mediator import ManagerMediator
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId as UnitID

from bot.combat.base_combat import BaseCombat
from bot.consts import COMMON_UNIT_IGNORE_TYPES
from cython_extensions import cy_closest_to, cy_in_attack_range, cy_distance_to_squared

if TYPE_CHECKING:
    from ares import AresBot, ManagerMediator


@dataclass
class SquadCombat(BaseCombat):
    """Execute behavior for a ground squad.

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

    def execute(self, units: list[Unit], **kwargs) -> None:
        """Execute squad movement.

        Parameters
        ----------
        units :
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        all_close_enemy : Units
        can_engage : bool
        target : Point2

        Returns
        -------
        """
        all_close_enemy: Units = kwargs["all_close_enemy"]
        always_fight_near_enemy: bool = kwargs["always_fight_near_enemy"]
        can_engage: bool = kwargs["can_engage"]
        main_squad: bool = kwargs["main_squad"]
        target: Point2 = kwargs["target"]
        air_grid: np.ndarray = self.mediator.get_air_grid
        ground_grid: np.ndarray = self.mediator.get_ground_grid

        valid_targets: list[Unit] = [
            u
            for u in all_close_enemy
            if not (u.is_cloaked or u.is_cloaked and u.is_revealed)
            and (not u.is_memory and u.type_id not in COMMON_UNIT_IGNORE_TYPES)
        ]

        only_enemy_units: list[Unit] = [
            u for u in valid_targets if u.type_id not in ALL_STRUCTURES
        ]

        for unit in units:
            grid = air_grid if unit.is_flying else ground_grid
            attacking_maneuver: CombatManeuver = CombatManeuver()

            if unit.can_attack_both:
                valid_targets = valid_targets
            else:
                valid_targets = [u for u in valid_targets if not u.is_flying]

            if valid_targets:
                # if flying target any dangers to air first
                if (
                    unit.is_flying
                    and unit.can_attack_both
                    and (
                        danger_to_air := [
                            u
                            for u in all_close_enemy
                            if (u.can_attack_air or u.type_id == UnitID.VOIDRAY)
                            and cy_distance_to_squared(u.position, unit.position)
                            <= (unit.ground_range + unit.radius + u.radius)
                        ]
                    )
                ):
                    attacking_maneuver.add(
                        ShootTargetInRange(unit=unit, targets=danger_to_air)
                    )
                # attack any units in range
                elif in_attack_range_e := cy_in_attack_range(unit, only_enemy_units):
                    # `ShootTargetInRange` will check weapon is ready
                    # otherwise it will not execute
                    attacking_maneuver.add(
                        ShootTargetInRange(unit=unit, targets=in_attack_range_e)
                    )
                # then anything else
                elif in_attack_range := cy_in_attack_range(unit, valid_targets):
                    attacking_maneuver.add(
                        ShootTargetInRange(unit=unit, targets=in_attack_range)
                    )

                if len(valid_targets) > 2 or always_fight_near_enemy:
                    if can_engage and unit.shield_health_percentage > 0.2:
                        enemy_target: Unit = cy_closest_to(unit.position, valid_targets)
                        if unit.ground_range < 3.0:
                            attacking_maneuver.add(
                                AMove(unit=unit, target=enemy_target)
                            )
                        else:
                            attacking_maneuver.add(
                                StutterUnitBack(
                                    unit=unit, target=enemy_target, grid=grid
                                )
                            )
                    # can't engage, stay safe but also attempt to get to target
                    else:
                        attacking_maneuver.add(KeepUnitSafe(unit=unit, grid=grid))
                        attacking_maneuver.add(
                            PathUnitToTarget(unit=unit, grid=grid, target=target)
                        )

            else:
                attacking_maneuver.add(
                    PathUnitToTarget(unit=unit, grid=grid, target=target)
                )
                attacking_maneuver.add(AMove(unit=unit, target=target))

            self.ai.register_behavior(attacking_maneuver)
