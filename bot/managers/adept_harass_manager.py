from typing import TYPE_CHECKING, Optional

import numpy as np
from ares import ManagerMediator
from ares.consts import (
    TOWNHALL_TYPES,
    EngagementResult,
    UnitRole,
    UnitTreeQueryType,
    WORKER_TYPES,
    VICTORY_CLOSE_OR_BETTER,
)
from ares.managers.manager import Manager
from ares.managers.squad_manager import UnitSquad
from cython_extensions.units_utils import cy_closest_to
from map_analyzer import MapData
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.adept_harass import AdeptHarass
from bot.combat.adept_shade_harass import AdeptShadeHarass
from bot.combat.base_unit import BaseUnit
from cython_extensions import cy_distance_to_squared

if TYPE_CHECKING:
    from ares import AresBot


class AdeptHarassManager(Manager):
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

        self._adept_harass: BaseUnit = AdeptHarass(ai, config, mediator)
        self._adept_shade_harass: BaseUnit = AdeptShadeHarass(ai, config, mediator)
        # adept tag to phase tag
        self._adept_to_phase: dict[int, int] = dict()
        # adept tag to target
        self._adept_targets: dict[int, Point2] = dict()
        # phase tag to target
        self._shade_targets: dict[int, Point2] = dict()

    async def update(self, iteration: int) -> None:
        adepts: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.CONTROL_GROUP_ONE, unit_type=UnitID.ADEPT
        )
        if len(adepts) == 0:
            return

        shades: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.CONTROL_GROUP_TWO, unit_type=UnitID.ADEPTPHASESHIFT
        )

        grid: np.ndarray = self.manager_mediator.get_ground_grid

        self._link_adept_to_shade(adepts, shades)
        cancel_shades_dict: dict = self._check_if_should_cancel_shades()
        self._calculate_adepts_and_phases_target(adepts, grid)

        self._adept_harass.execute(
            adepts,
            grid=grid,
            target_dict=self._adept_targets,
        )
        self._adept_shade_harass.execute(
            shades,
            cancel_shades_dict=cancel_shades_dict,
            grid=grid,
            target_dict=self._shade_targets,
        )

    def _link_adept_to_shade(self, adepts: Units, shades: Units) -> None:
        for shade in shades:
            adept: Unit = cy_closest_to(shade.position, adepts)
            self._adept_to_phase[adept.tag] = shade.tag

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

            # ground units near both groups
            units_near_adepts: Units = self.manager_mediator.get_units_in_range(
                start_points=[adept.position],
                distances=[11.0],
                query_tree=UnitTreeQueryType.EnemyGround,
            )[0]

            units_near_shades: Units = self.manager_mediator.get_units_in_range(
                start_points=[phase.position],
                distances=[11.0],
                query_tree=UnitTreeQueryType.EnemyGround,
            )[0]

            own_units: Units = self.manager_mediator.get_units_in_range(
                start_points=[adept.position],
                distances=[11.0],
                query_tree=UnitTreeQueryType.AllOwn,
            )[0]

            own_units_near_shade: Units = self.manager_mediator.get_units_in_range(
                start_points=[phase.position],
                distances=[11.0],
                query_tree=UnitTreeQueryType.AllOwn,
            )[0]

            # check current fight result, and potential fight result if shade finishes
            adept_result: EngagementResult = self.manager_mediator.can_win_fight(
                own_units=own_units,
                enemy_units=units_near_adepts,
                workers_do_no_damage=True,
            )

            potential_result: EngagementResult = self.manager_mediator.can_win_fight(
                own_units=own_units_near_shade,
                enemy_units=units_near_shades,
                workers_do_no_damage=True,
            )

            # simple scenario, adepts will get a better result fighting where the shades are
            # don't cancel shade
            if potential_result.value >= adept_result.value:
                cancel_shade_dict[phase.tag] = False
            # adepts looking better here?
            else:
                cancel_shade_dict[phase.tag] = True

        return cancel_shade_dict
