from itertools import cycle
from typing import TYPE_CHECKING, Optional

import numpy as np
from ares import ManagerMediator
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import (
    ShootTargetInRange,
    KeepUnitSafe,
    StutterUnitBack,
    PathUnitToTarget,
    AMove,
)
from ares.cache import property_cache_once_per_frame
from ares.consts import (
    TOWNHALL_TYPES,
    EngagementResult,
    UnitRole,
    UnitTreeQueryType,
    WORKER_TYPES,
    ALL_STRUCTURES,
)
from ares.managers.manager import Manager
from ares.managers.squad_manager import UnitSquad
from cython_extensions import cy_distance_to_squared, cy_pick_enemy_target
from cython_extensions.units_utils import (
    cy_closest_to,
    cy_find_units_center_mass,
    cy_in_attack_range,
)
from map_analyzer import MapData
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.adept_shade_harass import AdeptShadeHarass
from bot.combat.adept_harass import AdeptHarass
from bot.combat.base_unit import BaseUnit
from bot.consts import COMMON_UNIT_IGNORE_TYPES

if TYPE_CHECKING:
    from ares import AresBot


class CombatManager(Manager):
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

    @property_cache_once_per_frame
    def attack_target(self) -> Point2:
        """Quick attack target implementation, improve this later."""
        enemy_structure_pos: Optional[Point2] = None
        if enemy_structures := self.ai.enemy_structures.filter(
            lambda s: s.type_id
            not in {
                UnitID.CREEPTUMOR,
                UnitID.CREEPTUMORQUEEN,
                UnitID.CREEPTUMORBURROWED,
                UnitID.NYDUSCANAL,
            }
        ):
            enemy_structure_pos = enemy_structures.closest_to(
                self.manager_mediator.get_enemy_nat
            ).position

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

    async def update(self, iteration: int) -> None:
        grid: np.ndarray = self.manager_mediator.get_ground_grid
        army: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.ATTACKING
        )
        near_enemy: dict[int, Units] = self.manager_mediator.get_units_in_range(
            start_points=army,
            distances=15,
            query_tree=UnitTreeQueryType.AllEnemy,
            return_as_dict=True,
        )
        for s in army:
            if s.type_id == UnitID.OBSERVER:
                s.move(Point2(cy_find_units_center_mass(army, 8.0)[0]))
                continue

            attacking_maneuver: CombatManeuver = CombatManeuver()
            # we already calculated close enemies, use unit tag to retrieve them
            all_close: Units = near_enemy[s.tag].filter(
                lambda u: not u.is_memory and u.type_id not in COMMON_UNIT_IGNORE_TYPES
            )
            only_enemy_units: Units = all_close.filter(
                lambda u: u.type_id not in ALL_STRUCTURES
            )
            # enemy around, engagement control
            if all_close:
                if in_attack_range_e := cy_in_attack_range(s, only_enemy_units):
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
