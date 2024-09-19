from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from ares import ManagerMediator
from ares.consts import (
    ALL_STRUCTURES,
    TOWNHALL_TYPES,
    VICTORY_CLOSE_OR_BETTER,
    WORKER_TYPES,
    EngagementResult,
    UnitRole,
    UnitTreeQueryType,
)
from ares.managers.manager import Manager
from cython_extensions.units_utils import cy_closest_to
from map_analyzer import MapData
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.adept_harass import AdeptHarass
from bot.combat.adept_shade_harass import AdeptShadeHarass
from bot.combat.base_combat import BaseCombat
from bot.combat.map_control_adepts import MapControlAdepts
from bot.combat.map_control_shades import MapControlShades
from bot.consts import COMMON_UNIT_IGNORE_TYPES, RequestType
from bot.managers.deimos_mediator import DeimosMediator
from cython_extensions import cy_distance_to_squared

if TYPE_CHECKING:
    from ares import AresBot


class AdeptManager(Manager):
    deimos_mediator: DeimosMediator

    map_control_adepts: BaseCombat
    map_control_shades: BaseCombat

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

        self.deimos_requests_dict = {
            RequestType.GET_ADEPT_TO_PHASE: lambda kwargs: self._adept_to_phase,
        }

        self._adept_harass: BaseCombat = AdeptHarass(ai, config, mediator)
        self._adept_shade_harass: BaseCombat = AdeptShadeHarass(ai, config, mediator)

        # adept tag to phase tag
        self._adept_to_phase: dict[int, int] = dict()
        # adept tag to target
        self._adept_targets: dict[int, Point2] = dict()
        # phase tag to target
        self._shade_targets: dict[int, Point2] = dict()
        self._assigned_shades: set[int] = set()
        self._assigned_map_control_adept: bool = False

    def initialise(self) -> None:
        self.map_control_adepts: BaseCombat = MapControlAdepts(
            self.ai, self.config, self.ai.mediator
        )
        self.map_control_shades: BaseCombat = MapControlShades(
            self.ai, self.config, self.ai.mediator
        )

    def manager_request(
        self,
        receiver: str,
        request: RequestType,
        reason: str = None,
        **kwargs,
    ) -> Any:
        """Fetch information from this Manager so another Manager can use it.

        Parameters
        ----------
        receiver :
            This Manager.
        request :
            What kind of request is being made
        reason :
            Why the reason is being made
        kwargs :
            Additional keyword args if needed for the specific request, as determined
            by the function signature (if appropriate)

        Returns
        -------
        Optional[Union[Dict, DefaultDict, Coroutine[Any, Any, bool]]] :
            Everything that could possibly be returned from the Manager fits in there

        """
        return self.deimos_requests_dict[request](kwargs)

    async def update(self, iteration: int) -> None:
        all_adepts: Units = self.manager_mediator.get_own_army_dict[UnitID.ADEPT]
        if not all_adepts:
            return

        all_shades: Units = self.manager_mediator.get_own_army_dict[
            UnitID.ADEPTPHASESHIFT
        ]
        for shade in all_shades:
            role: UnitRole = UnitRole.CONTROL_GROUP_TWO
            if not self.deimos_mediator.get_enemy_rushed:
                role = UnitRole.MAP_CONTROL

            self.manager_mediator.assign_role(tag=shade.tag, role=role)

        # adepts are assigned defending by default
        defending_adepts: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.ATTACKING, unit_type=UnitID.ADEPT
        )
        self._manage_adept_roles(defending_adepts)

        grid: np.ndarray = self.manager_mediator.get_ground_grid

        self._link_adept_to_shade(all_adepts, all_shades)
        cancel_shades_dict: dict = self._check_if_should_cancel_shades()
        if self.ai.enemy_race == Race.Zerg:
            self._manage_map_control_adepts()
        self._manage_adept_harrass(cancel_shades_dict, grid)

    def _manage_adept_roles(self, defending_adepts: Units) -> None:
        # On this opening leave adepts on defence
        # if (
        #     self.ai.build_order_runner.chosen_opening == "AdeptVoidray"
        #     and self.ai.time < 280.0
        # ):
        #     for unit in defending_adepts:
        #
        #         self.manager_mediator.assign_role(tag=unit.tag, role=UnitRole.ATTACKING)

        for unit in defending_adepts:
            if self.manager_mediator.get_enemy_ling_rushed:
                role = UnitRole.DEFENDING
            else:
                role = UnitRole.HARASSING_ADEPT

            self.manager_mediator.assign_role(tag=unit.tag, role=role)

    def _manage_adept_harrass(self, cancel_shades_dict: dict, grid: np.ndarray) -> None:
        harrassing_adepts: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.HARASSING_ADEPT
        )
        shades: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.CONTROL_GROUP_TWO, unit_type=UnitID.ADEPTPHASESHIFT
        )

        self._calculate_adepts_and_phases_target(harrassing_adepts, grid)

        self._adept_harass.execute(
            harrassing_adepts,
            grid=grid,
            target_dict=self._adept_targets,
        )
        self._adept_shade_harass.execute(
            shades,
            cancel_shades_dict=cancel_shades_dict,
            grid=grid,
            target_dict=self._shade_targets,
        )

    def _manage_map_control_adepts(self) -> None:
        adepts: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.HARASSING_ADEPT
        )

        map_control_adepts: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.MAP_CONTROL, unit_type=UnitID.ADEPT
        )

        if not map_control_adepts and adepts and not self._assigned_map_control_adept:
            self._assigned_map_control_adept = True
            adept: Unit = adepts[0]
            self.manager_mediator.assign_role(tag=adept.tag, role=UnitRole.MAP_CONTROL)

        grid: np.ndarray = self.manager_mediator.get_ground_grid
        adept_to_shade: dict[int, int] = self.deimos_mediator.get_adept_to_phase
        for unit in map_control_adepts:
            if unit.tag in adept_to_shade:
                self.manager_mediator.assign_role(
                    tag=adept_to_shade[unit.tag], role=UnitRole.MAP_CONTROL
                )
        self.map_control_adepts.execute(map_control_adepts, grid=grid)

        for adept in map_control_adepts:
            if shade := self.ai.unit_tag_dict.get(
                self._adept_to_phase.get(adept.tag, 0)
            ):
                self.manager_mediator.assign_role(
                    tag=shade.tag, role=UnitRole.MAP_CONTROL
                )

        map_control_shades: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.MAP_CONTROL, unit_type=UnitID.ADEPTPHASESHIFT
        )
        self.map_control_shades.execute(map_control_shades)

    def _link_adept_to_shade(self, adepts: Units, shades: Units) -> None:
        for shade in shades:
            tag: int = shade.tag
            if tag in self._assigned_shades:
                continue
            adept: Unit = cy_closest_to(shade.position, adepts)
            self._adept_to_phase[adept.tag] = tag
            self._assigned_shades.add(tag)

    def _calculate_adepts_and_phases_target(
        self, adepts: Units, grid: np.ndarray
    ) -> None:
        """
        Work out where each adept should go
        Work out where each phase should go

        Parameters
        ----------
        adepts
        phases
        grid

        Returns
        -------

        """
        # on this opening we hold back till adept timing
        if (
            self.ai.build_order_runner.chosen_opening == "AdeptVoidray"
            and self.ai.time < 280.0
        ):
            for adept in adepts:
                adept_tag: int = adept.tag
                self._adept_targets[adept_tag] = self.ai.main_base_ramp.top_center
                if adept_tag in self._adept_to_phase:
                    if shade := self.ai.unit_tag_dict.get(
                        self._adept_to_phase[adept_tag]
                    ):
                        self._shade_targets[
                            shade.tag
                        ] = self.ai.main_base_ramp.top_center.towards(
                            self.ai.start_location, 6.0
                        )

            return

        map_data: MapData = self.manager_mediator.get_map_data_object
        # find all potential places we can harass
        enemy_townhalls: list[Unit] = [
            th
            for th in self.ai.enemy_structures
            if th.type_id in TOWNHALL_TYPES and th.build_progress > 0.95
        ]

        best_engagement_result: EngagementResult = EngagementResult.LOSS_EMPHATIC
        # looking for the least defended spot
        least_defended_target: Point2 = self.ai.enemy_start_locations[0]
        positions_to_check: list[Point2] = [th.position for th in enemy_townhalls]
        positions_to_check.append(self.ai.enemy_start_locations[0])

        # find the place that looks least defended
        for position_to_check in positions_to_check:
            result: EngagementResult = self.manager_mediator.can_win_fight(
                own_units=adepts,
                enemy_units=self.manager_mediator.get_units_in_range(
                    start_points=[position_to_check],
                    distances=[16.0],
                    query_tree=UnitTreeQueryType.AllEnemy,
                )[0],
                workers_do_no_damage=True,
            )
            if result.value > best_engagement_result.value:
                least_defended_target = position_to_check
                best_engagement_result = result

        # find nearest base to this least defended base
        close_target_near_least_defended: Point2 = least_defended_target
        closest_dist: int = 9999
        # look at paths to all other positions, find the closest one
        for position_to_check in positions_to_check:
            if position_to_check == least_defended_target:
                continue
            if path := map_data.pathfind(
                least_defended_target, position_to_check, grid, sensitivity=5
            ):
                if len(path) < closest_dist:
                    closest_dist = len(path)
                    close_target_near_least_defended = position_to_check

        # got no secondary target, special case
        single_target: bool = close_target_near_least_defended == least_defended_target

        # move the actual targets behind the mineral line
        least_defended_target = self.manager_mediator.get_behind_mineral_positions(
            th_pos=least_defended_target
        )[0]
        close_target_near_least_defended = (
            self.manager_mediator.get_behind_mineral_positions(
                th_pos=close_target_near_least_defended
            )[0]
        )

        for adept in adepts:
            adept_tag: int = adept.tag
            shade: Optional[Unit] = None
            if adept_tag in self._adept_to_phase:
                shade = self.ai.unit_tag_dict.get(self._adept_to_phase[adept_tag])

            # no alternative enemy bases to phase to
            if single_target:
                # adept far away, both phases and adepts have same target
                if (
                    cy_distance_to_squared(adept.position, least_defended_target)
                    > 400.0
                ):
                    self._adept_targets[adept_tag] = least_defended_target
                    if shade:
                        self._shade_targets[shade.tag] = least_defended_target
                # adept close, may need to shade away incase we need to escape
                else:
                    self._adept_targets[adept_tag] = least_defended_target
                    if shade:
                        if best_engagement_result in VICTORY_CLOSE_OR_BETTER:
                            self._shade_targets[shade.tag] = least_defended_target
                        else:
                            self._shade_targets[shade.tag] = self.ai.start_location
            # else we can phase between bases
            else:
                # adept close to target:
                # adept stay near target and phase go to secondary
                if (
                    cy_distance_to_squared(adept.position, least_defended_target)
                    < 400.0
                ):
                    self._adept_targets[adept_tag] = least_defended_target
                    if shade:
                        self._shade_targets[shade.tag] = least_defended_target

                # adept close to nearby target:
                # adept stay near nearby target and phase go to least defended
                elif (
                    cy_distance_to_squared(
                        adept.position, close_target_near_least_defended
                    )
                    < 400.0
                ):
                    self._adept_targets[adept_tag] = close_target_near_least_defended
                    if shade:
                        self._shade_targets[shade.tag] = least_defended_target
                # adept not near anything, both try to get near least_defended_target
                else:
                    self._adept_targets[adept_tag] = least_defended_target
                    if shade:
                        self._shade_targets[shade.tag] = least_defended_target

    def _check_if_should_cancel_shades(self) -> dict:
        cancel_shade_dict: dict[int, bool] = dict()
        for adept_tag, shade_tag in self._adept_to_phase.items():
            adept: Unit = self.ai.unit_tag_dict.get(adept_tag)
            phase: Unit = self.ai.unit_tag_dict.get(shade_tag)
            if not adept or not phase:
                continue

            if phase.buff_duration_remain > 10:
                cancel_shade_dict[phase.tag] = False
                continue

            # ground units near adepts
            units_near_adepts: Units = self.manager_mediator.get_units_in_range(
                start_points=[adept.position],
                distances=[10.0],
                query_tree=UnitTreeQueryType.EnemyGround,
            )[0]

            units_near_shades: Units = self.manager_mediator.get_units_in_range(
                start_points=[phase.position],
                distances=[10.0],
                query_tree=UnitTreeQueryType.EnemyGround,
            )[0]

            num_workers_near_shades: int = len(
                [
                    u
                    for u in units_near_shades
                    if u.type_id in WORKER_TYPES
                    and cy_distance_to_squared(phase.position, phase.position) < 39.0
                ]
            )

            num_workers_near_adepts: int = len(
                [
                    u
                    for u in units_near_adepts
                    if u.type_id in WORKER_TYPES
                    and cy_distance_to_squared(phase.position, phase.position) < 39.0
                ]
            )

            # adepts are already in a great spot! cancel shade
            if (
                num_workers_near_adepts >= 4
                and num_workers_near_adepts > num_workers_near_shades
            ):
                cancel_shade_dict[phase.tag] = True
                continue

            # idea here is, if there is nothing threatening ground, then finish shade
            # or if there happens to be enemy workers near shades
            if (
                len(
                    [
                        u
                        for u in units_near_shades
                        if u.can_attack and u.type_id not in WORKER_TYPES
                    ]
                )
                == 0
                or num_workers_near_shades >= 4
            ):
                cancel_shade_dict[phase.tag] = False
                continue

            units_near_adepts: list[Unit] = [
                u
                for u in units_near_adepts
                if u.type_id not in COMMON_UNIT_IGNORE_TYPES
                and u.type_id not in ALL_STRUCTURES
                and u.type_id not in WORKER_TYPES
            ]
            units_near_shades: list[Unit] = [
                u
                for u in units_near_shades
                if u.type_id not in COMMON_UNIT_IGNORE_TYPES
                and u.type_id not in ALL_STRUCTURES
                and u.type_id not in WORKER_TYPES
            ]
            if len(units_near_adepts) > len(units_near_shades):
                cancel_shade_dict[phase.tag] = False
            else:
                cancel_shade_dict[phase.tag] = True

        return cancel_shade_dict
