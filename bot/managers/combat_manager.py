from itertools import cycle
from typing import TYPE_CHECKING, Optional

import numpy as np
from ares import ManagerMediator
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    AMove,
    KeepUnitSafe,
    PathUnitToTarget,
    ShootTargetInRange,
    StutterUnitBack,
)
from ares.cache import property_cache_once_per_frame
from ares.consts import (
    ALL_STRUCTURES,
    WORKER_TYPES,
    EngagementResult,
    UnitRole,
    UnitTreeQueryType,
)
from ares.managers.manager import Manager
from cython_extensions.units_utils import (
    cy_closest_to,
    cy_find_units_center_mass,
    cy_in_attack_range,
)
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.base_unit import BaseUnit
from bot.consts import COMMON_UNIT_IGNORE_TYPES, STEAL_FROM_ROLES
from bot.managers.deimos_mediator import DeimosMediator
from cython_extensions import cy_distance_to_squared

if TYPE_CHECKING:
    from ares import AresBot


class CombatManager(Manager):
    deimos_mediator: DeimosMediator

    ATTACK_TARGET_IGNORE: set[UnitID] = {
        UnitID.CREEPTUMOR,
        UnitID.CREEPTUMORQUEEN,
        UnitID.CREEPTUMORBURROWED,
        UnitID.NYDUSCANAL,
    }
    defensive_voidrays: BaseUnit

    def __init__(
        self,
        ai: "AresBot",
        config: dict,
        mediator: ManagerMediator,
    ) -> None:
        """Handle all Reaper harass.

        This manager should assign Reapers to harass and call
        relevant combat classes to execute the harass.

        Parameters
        ----------
        ai :
            Bot object that will be running the game
        config :
            Dictionary with the data from the configuration file
        mediator :
            ManagerMediator used for getting information from other managers.
        """
        super().__init__(ai, config, mediator)
        self.expansions_generator = None
        self.current_base_target: Point2 = self.ai.enemy_start_locations[0]
        self.aggressive: bool = False

    @property_cache_once_per_frame
    def attack_target(self) -> Point2:
        """Quick attack target implementation, improve this later."""
        if (
            self.deimos_mediator.get_enemy_rushed
            and self.ai.time < 240.0
            and not self.manager_mediator.get_enemy_worker_rushed
        ):
            return self.ai.main_base_ramp.top_center

        enemy_structure_pos: Optional[Point2] = None
        if enemy_structures := self.ai.enemy_structures.filter(
            lambda s: s.type_id not in self.ATTACK_TARGET_IGNORE
        ):
            enemy_structure_pos = enemy_structures.closest_to(
                self.manager_mediator.get_enemy_nat
            ).position

        if (
            self.ai.build_order_runner.chosen_opening == "OneBaseTempests"
            and self.ai.time < 360.0
            and not enemy_structure_pos
        ):
            return self.ai.enemy_start_locations[0]

        own_center_mass, num_own = cy_find_units_center_mass(
            self.manager_mediator.get_units_from_role(role=UnitRole.ATTACKING),
            10,
        )
        # idea here is if we are near enemy structures/production, don't get distracted
        if (
            enemy_structure_pos
            and cy_distance_to_squared(own_center_mass, enemy_structure_pos) < 920.0
        ):
            return enemy_structure_pos

        enemy_center_mass, num_enemy = cy_find_units_center_mass(
            [
                u
                for u in self.manager_mediator.get_enemy_ground
                if u.type_id not in WORKER_TYPES and u.type_id not in ALL_STRUCTURES
            ],
            10,
        )

        all_close_enemy: Units = self.manager_mediator.get_units_in_range(
            start_points=[Point2(enemy_center_mass)],
            distances=11.5,
            query_tree=UnitTreeQueryType.EnemyGround,
        )[0]
        if self.ai.get_total_supply(all_close_enemy) >= 20:
            return Point2(enemy_center_mass)

        if enemy_structure_pos:
            return enemy_structure_pos
        else:
            # cycle through base locations
            if self.ai.is_visible(self.current_base_target):
                if not self.expansions_generator:
                    base_locations: list[Point2] = [
                        i for i in self.ai.expansion_locations_list
                    ]
                    self.expansions_generator = cycle(base_locations)

                self.current_base_target = next(self.expansions_generator)

            return self.current_base_target

    @property_cache_once_per_frame
    def main_fight_result(self) -> EngagementResult:
        attackers: Units = self.manager_mediator.get_units_from_roles(
            roles=STEAL_FROM_ROLES
        )
        army_mass: tuple[float, float] = cy_find_units_center_mass(attackers, 12.0)[0]
        army_near_mass: Units = attackers.filter(
            lambda u: cy_distance_to_squared(u.position, army_mass) < 150.0
        )

        return self.manager_mediator.can_win_fight(
            own_units=army_near_mass,
            enemy_units=self.manager_mediator.get_cached_enemy_army
            + self.ai.enemy_structures(UnitID.PLANETARYFORTRESS),
        )

    async def update(self, iteration: int) -> None:
        self._check_aggressive_status()
        self._manage_combat_roles()

        self._handle_attackers()
        # self._handle_defenders()

    def _manage_combat_roles(self) -> None:
        if self.aggressive:
            self.manager_mediator.switch_roles(
                from_role=UnitRole.DEFENDING, to_role=UnitRole.ATTACKING
            )
        else:
            self.manager_mediator.switch_roles(
                from_role=UnitRole.ATTACKING, to_role=UnitRole.DEFENDING
            )

    def _check_aggressive_status(self) -> None:
        self.aggressive = True
        # TODO: Example future logic
        # if self.aggressive:
        #     self.aggressive = self.main_fight_result not in LOSS_EMPHATIC_OR_WORSE
        # else:
        #     self.aggressive = self.main_fight_result in VICTORY_DECISIVE_OR_BETTER

    def _handle_attackers(self):
        air_grid: np.ndarray = self.manager_mediator.get_air_grid
        ground_grid: np.ndarray = self.manager_mediator.get_ground_grid
        army: Units = self.manager_mediator.get_units_from_role(role=UnitRole.ATTACKING)
        near_enemy: dict[int, Units] = self.manager_mediator.get_units_in_range(
            start_points=army,
            distances=15,
            query_tree=UnitTreeQueryType.AllEnemy,
            return_as_dict=True,
        )
        for s in army:
            grid: np.ndarray = air_grid if s.is_flying else ground_grid
            type_id: UnitID = s.type_id
            if type_id == UnitID.OBSERVER:
                s.move(Point2(cy_find_units_center_mass(army, 8.0)[0]))
                continue
            if type_id == UnitID.ZEALOT:
                s.attack(self.attack_target)
                continue

            attacking_maneuver: CombatManeuver = CombatManeuver()

            if type_id == UnitID.TEMPEST and s.shield_percentage < 0.3:
                attacking_maneuver.add(KeepUnitSafe(unit=s, grid=grid))

            # we already calculated close enemies, use unit tag to retrieve them
            all_close: Units = near_enemy[s.tag].filter(
                lambda u: (not u.is_cloaked or u.is_cloaked and u.is_revealed)
                and (not u.is_memory and u.type_id not in COMMON_UNIT_IGNORE_TYPES)
            )
            only_enemy_units: Units = all_close.filter(
                lambda u: u.type_id not in ALL_STRUCTURES
            )
            # enemy around, engagement control
            if all_close:
                if (
                    s.is_flying
                    and s.can_attack_ground
                    and (danger_to_air := [u for u in all_close if u.can_attack_air])
                ):
                    attacking_maneuver.add(
                        ShootTargetInRange(unit=s, targets=danger_to_air)
                    )
                elif in_attack_range_e := cy_in_attack_range(s, only_enemy_units):
                    # `ShootTargetInRange` will check weapon is ready
                    # otherwise it will not execute
                    attacking_maneuver.add(
                        ShootTargetInRange(unit=s, targets=in_attack_range_e)
                    )
                # then enemy structures
                elif in_attack_range := cy_in_attack_range(s, all_close):
                    attacking_maneuver.add(
                        ShootTargetInRange(unit=s, targets=in_attack_range)
                    )

                # low shield, keep protoss units safe
                if s.shield_percentage < 0.3:
                    attacking_maneuver.add(KeepUnitSafe(unit=s, grid=grid))

                else:
                    enemy_target: Unit = cy_closest_to(s.position, all_close)
                    attacking_maneuver.add(
                        StutterUnitBack(unit=s, target=enemy_target, grid=grid)
                    )

            # no enemy around, path to the attack target
            else:
                attacking_maneuver.add(
                    PathUnitToTarget(unit=s, grid=grid, target=self.attack_target)
                )
                attacking_maneuver.add(AMove(unit=s, target=self.attack_target))

            # DON'T FORGET TO REGISTER OUR COMBAT MANEUVER!!
            self.ai.register_behavior(attacking_maneuver)
