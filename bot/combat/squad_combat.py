from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    AttackTarget,
    KeepUnitSafe,
    PathUnitToTarget,
    ShootTargetInRange,
    StutterUnitBack,
    UseAbility,
)
from ares.consts import ALL_STRUCTURES
from ares.managers.manager_mediator import ManagerMediator
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.base_combat import BaseCombat
from bot.consts import COMMON_UNIT_IGNORE_TYPES
from cython_extensions import (
    cy_attack_ready,
    cy_closest_to,
    cy_distance_to,
    cy_in_attack_range,
    cy_pick_enemy_target,
)

if TYPE_CHECKING:
    from ares import AresBot, ManagerMediator

DANGER_TO_AIR: set[UnitID] = {
    UnitID.VOIDRAY,
    UnitID.PHOTONCANNON,
    UnitID.MISSILETURRET,
    UnitID.SPORECRAWLER,
    UnitID.BUNKER,
}


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
            if (not u.is_cloaked or u.is_cloaked and u.is_revealed)
            and (not u.is_burrowed or u.is_burrowed and u.is_visible)
            and not u.is_memory
            and u.type_id not in COMMON_UNIT_IGNORE_TYPES
        ]

        only_enemy_units: list[Unit] = [
            u for u in valid_targets if u.type_id not in ALL_STRUCTURES
        ]

        for unit in units:
            grid = air_grid if unit.is_flying else ground_grid
            attacking_maneuver: CombatManeuver = CombatManeuver()
            # TODO: improve zealots
            if unit.type_id == UnitID.ZEALOT:
                attacking_maneuver.add(AMove(unit=unit, target=target))
                self.ai.register_behavior(attacking_maneuver)
                continue

            if unit.can_attack_both:
                valid_targets = valid_targets
            elif unit.can_attack_air:
                valid_targets = [u for u in valid_targets if u.is_flying]
            else:
                valid_targets = [u for u in valid_targets if not u.is_flying]

            if unit.type_id == UnitID.OBSERVER:
                attacking_maneuver.add(KeepUnitSafe(unit=unit, grid=grid))
                attacking_maneuver.add(
                    PathUnitToTarget(unit=unit, grid=grid, target=target)
                )

            elif valid_targets:
                # if flying target any dangers to air first
                if (
                    unit.is_flying
                    and unit.can_attack_both
                    and (
                        danger_to_air := [
                            u
                            for u in all_close_enemy
                            if (u.can_attack_air or u.type_id in DANGER_TO_AIR)
                            and cy_distance_to(u.position, unit.position)
                            <= (
                                (
                                    unit.ground_range
                                    if not u.is_flying
                                    else unit.air_range
                                )
                                + unit.radius
                                + u.radius
                            )
                        ]
                    )
                ):
                    if f_danger := [e for e in danger_to_air if e.is_flying]:
                        e_target: Unit = cy_pick_enemy_target(f_danger)
                    else:
                        e_target: Unit = cy_pick_enemy_target(danger_to_air)
                    if target and cy_attack_ready(self.ai, unit, e_target):
                        attacking_maneuver.add(AttackTarget(unit=unit, target=e_target))

                # attack any units in range
                if in_attack_range_e := cy_in_attack_range(unit, only_enemy_units):
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

                ground: list[Unit] = [
                    u
                    for u in valid_targets
                    if not u.is_flying and u.type_id not in ALL_STRUCTURES
                ]
                if unit.shield_health_percentage < 0.25:
                    attacking_maneuver.add(KeepUnitSafe(unit=unit, grid=grid))
                elif len(ground) > 0 or always_fight_near_enemy:
                    if unit.has_buff(BuffId.LOCKON):
                        attacking_maneuver.add(
                            UseAbility(
                                AbilityId.MOVE_MOVE, unit, self.ai.start_location
                            )
                        )
                    elif can_engage:
                        enemy_target: Unit = cy_closest_to(unit.position, valid_targets)
                        # enemy_target: Unit = cy_pick_enemy_target(valid_targets)
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
                        # attacking_maneuver.add(
                        #     PathUnitToTarget(unit=unit, grid=grid, target=target)
                        # )
                else:
                    attacking_maneuver.add(KeepUnitSafe(unit=unit, grid=grid))
                    attacking_maneuver.add(
                        PathUnitToTarget(
                            unit=unit, grid=grid, target=target, success_at_distance=14
                        )
                    )
                    attacking_maneuver.add(AMove(unit, target))

            else:
                attacking_maneuver.add(
                    PathUnitToTarget(
                        unit=unit, grid=grid, target=target, success_at_distance=6.5
                    )
                )
                if not unit.orders:
                    attacking_maneuver.add(AMove(unit=unit, target=target))

            self.ai.register_behavior(attacking_maneuver)
