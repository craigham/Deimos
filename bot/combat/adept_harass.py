from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

import numpy as np
from ares import ManagerMediator, UnitTreeQueryType
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    KeepUnitSafe,
    PathUnitToTarget,
    ShootTargetInRange,
    StutterUnitBack,
    UseAbility,
)
from ares.consts import VICTORY_DECISIVE_OR_BETTER, EngagementResult
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from src.ares.consts import ALL_STRUCTURES, WORKER_TYPES

from bot.combat.base_combat import BaseCombat
from bot.consts import COMMON_UNIT_IGNORE_TYPES
from cython_extensions import (
    cy_attack_ready,
    cy_closest_to,
    cy_in_attack_range,
    cy_pick_enemy_target,
)

if TYPE_CHECKING:
    from ares import AresBot

STATIC_DEF: set[UnitID] = {
    UnitID.BUNKER,
    UnitID.PLANETARYFORTRESS,
    UnitID.PHOTONCANNON,
    UnitID.SPINECRAWLER,
}


@dataclass
class AdeptHarass(BaseCombat):
    """Execute behavior for Oracle harass.

    Called from `AdeptManager`

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
        """Actually execute oracle harass.

        Parameters
        ----------
        units :
            The squad we want to control.
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        grid : np.ndarray
        target_dict : Dict
        """
        grid: np.ndarray = kwargs["grid"]
        target_dict: dict[int, Point2] = kwargs["target_dict"]
        phase_ability: AbilityId = AbilityId.ADEPTPHASESHIFT_ADEPTPHASESHIFT
        near_enemy: dict[int, Units] = self.mediator.get_units_in_range(
            start_points=units,
            distances=15,
            query_tree=UnitTreeQueryType.EnemyGround,
            return_as_dict=True,
        )
        for unit in units:
            unit_tag: int = unit.tag

            all_close: list[Unit] = [
                u
                for u in near_enemy[unit_tag]
                if not u.is_memory
                and u.type_id not in COMMON_UNIT_IGNORE_TYPES
                and not u.is_snapshot
            ]
            only_enemy_units: list[Unit] = [
                u for u in all_close if u.type_id not in ALL_STRUCTURES
            ]
            workers: list[Unit] = [u for u in all_close if u.type_id in WORKER_TYPES]

            target = target_dict[unit_tag]

            adept_harass: CombatManeuver = CombatManeuver()

            # use shade if available
            if phase_ability in unit.abilities:
                adept_harass.add(UseAbility(phase_ability, unit, target))
            elif unit.has_buff(BuffId.LOCKON):
                adept_harass.add(
                    UseAbility(AbilityId.MOVE_MOVE, unit, self.ai.start_location)
                )
            # fighting logic
            elif all_close:
                can_take_fight: bool = self._can_take_fight(unit, all_close)
                if len([u for u in all_close if u.type_id in STATIC_DEF]) > 0:
                    can_take_fight = False
                if in_attack_range := cy_in_attack_range(unit, workers):
                    # `ShootTargetInRange` will check weapon is ready
                    # otherwise it will not execute
                    adept_harass.add(
                        ShootTargetInRange(unit=unit, targets=in_attack_range)
                    )
                elif in_attack_range := cy_in_attack_range(unit, only_enemy_units):
                    # `ShootTargetInRange` will check weapon is ready
                    # otherwise it will not execute
                    adept_harass.add(
                        ShootTargetInRange(unit=unit, targets=in_attack_range)
                    )
                # then enemy structures
                if not only_enemy_units:
                    if in_attack_range := cy_in_attack_range(unit, all_close):
                        adept_harass.add(
                            ShootTargetInRange(unit=unit, targets=in_attack_range)
                        )
                if can_take_fight and unit.shield_health_percentage > 0.2:
                    if only_enemy_units:
                        adept_harass.add(
                            StutterUnitBack(
                                unit,
                                cy_closest_to(unit.position, only_enemy_units),
                                grid=grid,
                            )
                        )
                    else:
                        adept_harass.add(
                            PathUnitToTarget(unit, grid, target, sense_danger=False)
                        )
                else:
                    adept_harass.add(KeepUnitSafe(unit, grid))
            # moving on map
            else:
                adept_harass.add(
                    PathUnitToTarget(unit, grid, target, sense_danger=False)
                )

            self.ai.register_behavior(adept_harass)

    def _pick_target(self, units: list[Unit], targets: list[Unit]) -> Union[Unit, None]:
        """If all close targets have same health, pick the closest one.
        Otherwise, pick enemy with the lowest health.

        Parameters
        ----------
        units :
            The units we are choosing a target for.
        targets : list[Unit]
            The targets the adepts can choose from.

        Returns
        -------
        Union[Unit, None] :
            Optional thing to shoot at.

        """
        if not targets:
            return

        all_targets: list[Unit] = []
        light_targets: list[Unit] = []
        for unit in targets:
            if all([cy_attack_ready(self.ai, u, unit) for u in units]):
                if unit.is_light:
                    light_targets.append(unit)
                all_targets.append(unit)

        if light_targets:
            return cy_pick_enemy_target(light_targets)
        elif all_targets:
            return cy_pick_enemy_target(all_targets)

    def _can_take_fight(self, unit: Unit, all_close: list[Unit]) -> bool:
        result: EngagementResult = self.mediator.can_win_fight(
            own_units=self.mediator.get_units_in_range(
                start_points=[unit.position],
                distances=[11.0],
                query_tree=UnitTreeQueryType.AllOwn,
            )[0],
            enemy_units=all_close,
            workers_do_no_damage=True,
        )
        return result in VICTORY_DECISIVE_OR_BETTER
