from typing import TYPE_CHECKING, Any

from ares import ManagerMediator, UnitRole
from ares.behaviors.macro import (
    AutoSupply,
    MacroPlan,
    Mining,
    ProductionController,
    SpawnController,
)
from ares.behaviors.macro.build_workers import BuildWorkers
from ares.behaviors.macro.gas_building_controller import GasBuildingController
from ares.managers.manager import Manager
from sc2.unit import Unit
from sc2.units import Units

from bot.consts import RequestType
from bot.managers.deimos_mediator import DeimosMediator
from cython_extensions import cy_distance_to_squared

if TYPE_CHECKING:
    from ares import AresBot


class MacroManager(Manager):
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

    @property
    def gas_buildings_required(self) -> int:
        supply_workers: float = self.ai.supply_workers
        if supply_workers < 20.0:
            return 0

        gas_required: int = 3 if supply_workers < 48 else 6

        return gas_required

    async def update(self, iteration: int) -> None:
        self._do_mining()
        if self.ai.build_order_runner.build_completed:
            max_probes: int = min(66, 22 * len(self.ai.townhalls))

            macro_plan: MacroPlan = MacroPlan()
            macro_plan.add(AutoSupply(self.ai.start_location))
            macro_plan.add(BuildWorkers(max_probes))
            macro_plan.add(
                GasBuildingController(
                    to_count=self.gas_buildings_required,
                    max_pending=1 if self.ai.supply_workers < 60 else 3,
                )
            )
            macro_plan.add(
                ProductionController(
                    self.deimos_mediator.get_army_comp,
                    base_location=self.ai.start_location,
                )
            )
            macro_plan.add(
                SpawnController(
                    self.deimos_mediator.get_army_comp,
                    spawn_target=self.manager_mediator.get_own_nat,
                    freeflow_mode=self.ai.minerals > 500 and self.ai.vespene > 500,
                    ignore_proportions_below_unit_count=4,
                )
            )

            self.ai.register_behavior(macro_plan)

    def _do_mining(self):
        num_workers_per_gas: int = 3
        gatherers: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.GATHERING
        )
        if (
            self.manager_mediator.get_enemy_worker_rushed and len(gatherers) < 21
        ) or len(gatherers) < 12:
            num_workers_per_gas: int = 0
        self.ai.register_behavior(Mining(workers_per_gas=num_workers_per_gas))
