from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ares import ManagerMediator
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    AttackTarget,
    KeepUnitSafe,
    PathUnitToTarget,
    ShootTargetInRange,
    UseAbility,
)
from ares.consts import ALL_STRUCTURES, UnitTreeQueryType
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.base_combat import BaseCombat
from cython_extensions import cy_closest_to, cy_in_attack_range

if TYPE_CHECKING:
    from ares import AresBot


@dataclass
class PhoenixHarass(BaseCombat):
    """Execute behavior for Oracle harass.

    Called from `OracleManager`

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

    @property
    def safe_spot(self) -> Point2:
        """Get safe spot oracle can retreat to inbetween harass.

        Returns
        -------
        Point2 :
            Safe spot near the middle of the map.
        """
        return self.mediator.find_closest_safe_spot(
            from_pos=self.ai.game_info.map_center, grid=self.mediator.get_air_grid
        )

    def execute(self, units: Units, **kwargs) -> None:
        """Actually execute oracle harass.

        Parameters
        ----------
        units : list[Unit]
            The units we want OracleHarass to control.
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        """
        can_engage: bool = kwargs["can_engage"]
        close_own: Units = kwargs["close_own"]
        main_squad: bool = kwargs["main_squad"]
        pos_of_main_squad: Point2 = kwargs["pos_of_main_squad"]
        target: Point2 = kwargs["target"]
        everything_near_phoenixes: dict[int, Units] = self.mediator.get_units_in_range(
            start_points=units,
            distances=12.0,
            query_tree=UnitTreeQueryType.AllEnemy,
            return_as_dict=True,
        )
        air_grid: np.ndarray = self.mediator.get_air_grid
        avoidance_grid: np.ndarray = self.mediator.get_air_avoidance_grid
        ground_to_air_grid: np.ndarray = self.mediator.get_ground_to_air_grid

        for unit in units:
            close_enemy: Units = everything_near_phoenixes[unit.tag].filter(
                lambda u: u.type_id not in ALL_STRUCTURES
                or u.type_id
                in {
                    UnitID.PHOTONCANNON,
                    UnitID.BUNKER,
                    UnitID.MISSILETURRET,
                    UnitID.SPORECRAWLER,
                }
            )
            maneuver: CombatManeuver = CombatManeuver()

            # keep safe from dangerous effects (storms, biles etc)
            maneuver.add(KeepUnitSafe(unit, avoidance_grid))

            if close_enemy:
                air: list[Unit]
                ground: list[Unit]
                ground, air = self.ai.split_ground_fliers(
                    close_enemy, return_as_lists=True
                )
                ground = [g for g in ground if not g.is_structure]
                lift_ready: bool = (
                    unit.shield_percentage > 0.1
                    and AbilityId.GRAVITONBEAM_GRAVITONBEAM in unit.abilities
                )
                # check we have enough around to hit air
                if lift_ready:
                    lift_ready = len([u for u in close_own if u.can_attack_air]) >= 3

                liftable: list[Unit] = [
                    u
                    for u in ground
                    if u.type_id
                    not in {
                        UnitID.BROODLING,
                        UnitID.EGG,
                        UnitID.LARVA,
                        UnitID.ZERGLING,
                        UnitID.MULE,
                    }
                ]
                maneuver.add(ShootTargetInRange(unit, air))
                if can_engage:
                    if unit.shield_percentage < 0.1:
                        maneuver.add(KeepUnitSafe(unit, air_grid))

                    elif air:
                        lifted: list[Unit] = [
                            u for u in air if u.has_buff(BuffId.GRAVITONBEAM)
                        ]
                        if lifted:
                            maneuver.add(
                                AttackTarget(unit, cy_closest_to(unit.position, lifted))
                            )
                        # stay out of range of ground to air units
                        maneuver.add(KeepUnitSafe(unit, ground_to_air_grid))
                        # already have ShootTargetInRange, so just try to keep in range
                        if not cy_in_attack_range(unit, air):
                            maneuver.add(
                                AMove(unit, cy_closest_to(unit.position, air).position)
                            )
                        # in range of air, keep safe as we can
                        else:
                            maneuver.add(KeepUnitSafe(unit, air_grid))

                    elif liftable and lift_ready:
                        lift_target: Unit = self._get_lift_target(unit, liftable)
                        maneuver.add(
                            UseAbility(
                                AbilityId.GRAVITONBEAM_GRAVITONBEAM,
                                unit,
                                lift_target,
                            )
                        )
                    else:
                        maneuver.add(KeepUnitSafe(unit, air_grid))
                        maneuver.add(
                            UseAbility(AbilityId.MOVE_MOVE, unit, pos_of_main_squad)
                        )
                else:
                    if not main_squad:
                        maneuver.add(
                            PathUnitToTarget(
                                unit,
                                air_grid,
                                pos_of_main_squad,
                                success_at_distance=8.0,
                            )
                        )
                    maneuver.add(KeepUnitSafe(unit, air_grid))
            else:
                move_to: Point2 = target if main_squad else pos_of_main_squad
                maneuver.add(PathUnitToTarget(unit, air_grid, move_to))

            self.ai.register_behavior(maneuver)

    def _get_lift_target(self, unit: Unit, liftable: list[Unit]) -> Unit:
        if can_attack_air := [u for u in liftable if u.can_attack_air]:
            return cy_closest_to(unit.position, can_attack_air)
        elif tanks := [
            u
            for u in liftable
            if u.type_id in {UnitID.SIEGETANK, UnitID.SIEGETANKSIEGED}
        ]:
            return cy_closest_to(unit.position, tanks)
        else:
            return cy_closest_to(unit.position, liftable)
