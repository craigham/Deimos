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
    VICTORY_EMPHATIC_OR_BETTER,
    LOSS_MARGINAL_OR_WORSE,
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

from ares.managers.squad_manager import UnitSquad
from bot.combat.base_combat import BaseCombat
from bot.combat.flying_squad_combat import FlyingSquadCombat
from bot.combat.ground_squad_combat import GroundSquadCombat
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
    SQUAD_ENGAGE_THRESHOLD: set[EngagementResult] = VICTORY_EMPHATIC_OR_BETTER
    SQUAD_DISENGAGE_THRESHOLD: set[EngagementResult] = LOSS_MARGINAL_OR_WORSE
    defensive_voidrays: BaseCombat

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
        self._squad_id_to_engage_tracker: dict[str, bool] = dict()

        self.ground_squad_combat: BaseCombat = GroundSquadCombat(ai, config, mediator)
        self.flying_squad_combat: BaseCombat = FlyingSquadCombat(ai, config, mediator)

    @property_cache_once_per_frame
    def attack_target(self) -> Point2:
        """Quick attack target implementation, improve this later."""
        if (
            self.ai.build_order_runner.chosen_opening == "OneBaseTempests"
            and self.ai.time < 480.0
            and (air := self.ai.enemy_units({UnitID.VOIDRAY, UnitID.TEMPEST}))
        ):
            return cy_closest_to(self.ai.start_location, air).position

        if (
            self.deimos_mediator.get_enemy_rushed
            and self.ai.time < 240.0
            and not self.manager_mediator.get_enemy_worker_rushed
        ) or (
            self.ai.build_order_runner.chosen_opening == "OneBaseTempests"
            and len(self.manager_mediator.get_own_army_dict[UnitID.TEMPEST]) <= 3
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

        self._manage_main_combat()
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

    def _manage_main_combat(self) -> None:
        squads: list[UnitSquad] = self.manager_mediator.get_squads(
            role=UnitRole.ATTACKING, squad_radius=9.0
        )
        if len(squads) == 0:
            return

        army: Units = self.manager_mediator.get_units_from_role(role=UnitRole.ATTACKING)

        pos_of_main_squad: Point2 = self.manager_mediator.get_position_of_main_squad(
            role=UnitRole.ATTACKING
        )

        for squad in squads:
            move_to: Point2 = self.attack_target if squad.main_squad else pos_of_main_squad
            all_close_enemy: Units = self.manager_mediator.get_units_in_range(
                start_points=[squad.squad_position],
                distances=18.5,
                query_tree=UnitTreeQueryType.AllEnemy,
            )[0].filter(lambda u: u.type_id not in COMMON_UNIT_IGNORE_TYPES)

            self._track_squad_engagement(army, squad)
            can_engage: bool = self._squad_id_to_engage_tracker[squad.squad_id]

            ground, flying = self.ai.split_ground_fliers(
                squad.squad_units, return_as_lists=True
            )

            if flying:
                self.flying_squad_combat.execute(
                    flying,
                    all_close_enemy=all_close_enemy,
                    can_engage=can_engage,
                    main_squad=squad.main_squad,
                    target=move_to,
                )
            if ground:
                self.ground_squad_combat.execute(
                    ground,
                    all_close_enemy=all_close_enemy,
                    can_engage=can_engage,
                    main_squad=squad.main_squad,
                    target=move_to,
                )

    def _track_squad_engagement(self, attackers: Units, squad: UnitSquad) -> None:
        """
        Not only do we check units in this squad, we should check all
        our units with UnitRole.Attacking, since another squad might be
        situated in a flank position etc.

        Parameters
        ----------
        close_enemy
        squad

        Returns
        -------

        """
        close_enemy: Units = self.manager_mediator.get_units_in_range(
            start_points=[squad.squad_position],
            distances=25.5,
            query_tree=UnitTreeQueryType.AllEnemy,
        )[0]

        squad_id: str = squad.squad_id
        if squad_id not in self._squad_id_to_engage_tracker:
            self._squad_id_to_engage_tracker[squad_id] = False

        # no enemy nearby, makes no sense to engage
        if not close_enemy:
            self._squad_id_to_engage_tracker[squad_id] = False
            return

        enemy_pos: Point2 = close_enemy.center

        own_attackers_nearby: Units = attackers.filter(
            lambda a: cy_distance_to_squared(a.position, enemy_pos) < 240.0
        )

        fight_result: EngagementResult = self.manager_mediator.can_win_fight(
            own_units=own_attackers_nearby, enemy_units=close_enemy
        )

        # currently engaging, see if we should disengage
        if self._squad_id_to_engage_tracker[squad.squad_id]:
            if fight_result in self.SQUAD_DISENGAGE_THRESHOLD:
                self._squad_id_to_engage_tracker[squad.squad_id] = False
        # not engaging, check if we can
        elif fight_result in self.SQUAD_ENGAGE_THRESHOLD:
            self._squad_id_to_engage_tracker[squad.squad_id] = True
