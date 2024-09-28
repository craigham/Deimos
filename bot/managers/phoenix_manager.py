from typing import TYPE_CHECKING

from ares import ManagerMediator
from ares.consts import (
    ALL_STRUCTURES,
    LOSS_MARGINAL_OR_WORSE,
    TOWNHALL_TYPES,
    VICTORY_EMPHATIC_OR_BETTER,
    EngagementResult,
    UnitRole,
    UnitTreeQueryType,
)
from ares.managers.manager import Manager
from ares.managers.squad_manager import UnitSquad
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.base_combat import BaseCombat
from bot.combat.phoenix_harass import PhoenixHarass
from bot.consts import COMMON_UNIT_IGNORE_TYPES, STEAL_FROM_ROLES
from bot.managers.deimos_mediator import DeimosMediator
from cython_extensions import cy_closest_to

if TYPE_CHECKING:
    from ares import AresBot


class PhoenixManager(Manager):
    deimos_mediator: DeimosMediator

    SQUAD_ENGAGE_THRESHOLD: set[EngagementResult] = VICTORY_EMPHATIC_OR_BETTER
    SQUAD_DISENGAGE_THRESHOLD: set[EngagementResult] = LOSS_MARGINAL_OR_WORSE

    def __init__(
        self,
        ai: "AresBot",
        config: dict,
        mediator: ManagerMediator,
    ) -> None:
        """Handle all Phoenix harass.

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

        self._phoenix_harass: BaseCombat = PhoenixHarass(ai, config, mediator)

        # TODO: make the target more sophisticated
        self.phoenix_harass_target: Point2 = ai.enemy_start_locations[0]
        self._squad_id_to_engage_tracker: dict[str, bool] = dict()

    def _update_phoenix_harass_target(self, phoenixes: list[Unit]) -> None:
        if enemy_harass := self.ai.enemy_units({UnitID.BANSHEE, UnitID.MUTALISK}):
            self.phoenix_harass_target = cy_closest_to(
                self.ai.start_location, enemy_harass
            ).position
            return

        enemy_townhalls: Units = self.ai.enemy_structures(TOWNHALL_TYPES)

        best_result: EngagementResult = EngagementResult.LOSS_EMPHATIC
        best_target: Point2 = self.ai.enemy_start_locations[0]

        for th in enemy_townhalls:
            if th.is_flying:
                continue
            target_pos: Point2 = th.position

            close_enemy: Units = self.manager_mediator.get_units_in_range(
                start_points=[target_pos],
                distances=[11.0],
                query_tree=UnitTreeQueryType.AllEnemy,
            )[0]

            fight_result: EngagementResult = self.manager_mediator.can_win_fight(
                own_units=phoenixes, enemy_units=close_enemy
            )
            if fight_result.value >= best_result.value:
                best_result = fight_result
                best_target = target_pos

        self.phoenix_harass_target = best_target

    async def update(self, iteration: int) -> None:
        self._assign_phoenix_roles()
        self._control_phoenixes()

    def _assign_phoenix_roles(self) -> None:
        if defending_phoenixes := self.manager_mediator.get_units_from_roles(
            roles=STEAL_FROM_ROLES, unit_type=UnitID.PHOENIX
        ):
            self.manager_mediator.batch_assign_role(
                tags=defending_phoenixes.tags, role=UnitRole.HARASSING_PHOENIX
            )

    def _control_phoenixes(self):
        phoenix_squads: list[UnitSquad] = self.manager_mediator.get_squads(
            role=UnitRole.HARASSING_PHOENIX, squad_radius=9.0
        )
        if len(phoenix_squads) == 0:
            return

        pos_of_main_squad: Point2 = self.manager_mediator.get_position_of_main_squad(
            role=UnitRole.HARASSING_PHOENIX
        )
        for squad in phoenix_squads:
            if squad.main_squad:
                self._update_phoenix_harass_target(squad.squad_units)
            all_close_own: Units = self.manager_mediator.get_units_in_range(
                start_points=[squad.squad_position],
                distances=10.5,
                query_tree=UnitTreeQueryType.AllOwn,
            )[0]
            all_close_enemy: Units = self.manager_mediator.get_units_in_range(
                start_points=[squad.squad_position],
                distances=16.5,
                query_tree=UnitTreeQueryType.AllEnemy,
            )[0].filter(lambda u: u.type_id not in COMMON_UNIT_IGNORE_TYPES)

            self._track_engagement(squad, all_close_own, all_close_enemy)
            can_engage: bool = self._squad_id_to_engage_tracker[squad.squad_id]
            self._phoenix_harass.execute(
                squad.squad_units,
                can_engage=can_engage,
                close_own=all_close_own,
                main_squad=squad.main_squad,
                pos_of_main_squad=pos_of_main_squad,
                target=self.phoenix_harass_target,
            )

    def _track_engagement(
        self, squad: UnitSquad, all_close_own: Units, all_close_enemy: Units
    ) -> None:
        only_units: list[Unit] = [
            u for u in all_close_enemy if u.type_id not in ALL_STRUCTURES
        ]

        squad_id: str = squad.squad_id
        if squad_id not in self._squad_id_to_engage_tracker:
            self._squad_id_to_engage_tracker[squad_id] = False

        # no enemy nearby, makes no sense to engage
        if not only_units:
            self._squad_id_to_engage_tracker[squad_id] = False
            return

        fight_result: EngagementResult = self.manager_mediator.can_win_fight(
            own_units=all_close_own, enemy_units=only_units
        )

        # currently engaging, see if we should disengage
        if self._squad_id_to_engage_tracker[squad.squad_id]:
            if fight_result in self.SQUAD_DISENGAGE_THRESHOLD:
                self._squad_id_to_engage_tracker[squad.squad_id] = False
        # not engaging, check if we can
        elif fight_result in self.SQUAD_ENGAGE_THRESHOLD:
            self._squad_id_to_engage_tracker[squad.squad_id] = True
