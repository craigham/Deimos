from typing import TYPE_CHECKING

from ares import ManagerMediator
from ares.consts import ALL_STRUCTURES, WORKER_TYPES, UnitRole, UnitTreeQueryType
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.unit import Unit
from sc2.units import Units

from bot.managers.deimos_mediator import DeimosMediator
from cython_extensions import cy_closest_to, cy_distance_to_squared

if TYPE_CHECKING:
    from ares import AresBot


class ScoutManager(Manager):
    deimos_mediator: DeimosMediator

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

    async def update(self, iteration: int) -> None:
        self._probe_proxy_denier()

    def _probe_proxy_denier(self):
        """Turn scouting probe, into a proxy denier

        Returns
        -------

        """
        if self.deimos_mediator.get_enemy_proxies:
            worker_scouts: Units = self.manager_mediator.get_units_from_role(
                role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=self.ai.worker_type
            )
            for scout in worker_scouts:
                self.manager_mediator.assign_role(tag=scout.tag, role=UnitRole.SCOUTING)

        if probes := self.manager_mediator.get_units_from_role(
            role=UnitRole.SCOUTING, unit_type=UnitID.PROBE
        ):
            ground_near_workers: dict[
                int, Units
            ] = self.manager_mediator.get_units_in_range(
                start_points=probes,
                distances=15,
                query_tree=UnitTreeQueryType.EnemyGround,
                return_as_dict=True,
            )
            for probe in probes:
                enemy_near_worker: Units = ground_near_workers[probe.tag]
                if probe.shield_percentage < 0.1:
                    self.manager_mediator.assign_role(
                        tag=probe.tag, role=UnitRole.GATHERING
                    )
                elif enemy_workers := [
                    u
                    for u in enemy_near_worker
                    if u.type_id in WORKER_TYPES
                    and cy_distance_to_squared(
                        u.position, self.manager_mediator.get_enemy_nat
                    )
                    > 2600.0
                ]:
                    probe.attack(cy_closest_to(probe.position, enemy_workers))
                    continue

                elif structures := [
                    u
                    for u in enemy_near_worker
                    if u.type_id in ALL_STRUCTURES
                    and cy_distance_to_squared(
                        u.position, self.manager_mediator.get_enemy_nat
                    )
                    > 1600.0
                ]:
                    probe.attack(cy_closest_to(probe.position, structures))

                else:
                    self.manager_mediator.assign_role(
                        tag=probe.tag, role=UnitRole.GATHERING
                    )
