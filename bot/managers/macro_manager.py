from typing import TYPE_CHECKING

from sc2.data import Race

from ares import ManagerMediator, UnitRole
from ares.behaviors.macro import (
    AutoSupply,
    BuildWorkers,
    ExpansionController,
    GasBuildingController,
    MacroPlan,
    Mining,
    ProductionController,
    SpawnController,
)
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.units import Units

from bot.managers.deimos_mediator import DeimosMediator

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

        self._main_building_location: Point2 = self.ai.start_location
        self._workers_per_gas: int = 3

    @property
    def can_expand(self) -> bool:
        if self.deimos_mediator.get_enemy_rushed and self.ai.supply_army < 22:
            return False

        return self.ai.minerals > 500

    @property
    def gas_buildings_required(self) -> int:
        supply_workers: float = self.ai.supply_workers
        if supply_workers < 20.0:
            return 0

        gas_required: int = 3 if supply_workers < 40 else 100

        return gas_required

    async def update(self, iteration: int) -> None:
        if iteration % 16 == 0:
            self._check_building_location()

        self._do_mining()
        if self.ai.build_order_runner.build_completed:
            max_probes: int = min(74, 22 * len(self.ai.townhalls))
            if (
                not self.manager_mediator.get_enemy_expanded
                and self.ai.supply_army < 28
            ):
                if self.deimos_mediator.get_enemy_rushed:
                    max_probes = 25
                elif self.ai.enemy_race == Race.Protoss:
                    max_probes = 29

            macro_plan: MacroPlan = MacroPlan()
            macro_plan.add(AutoSupply(self._main_building_location))
            macro_plan.add(BuildWorkers(max_probes))
            if (
                self.ai.build_order_runner.chosen_opening == "PhoenixEconomic"
                and self.ai.supply_used < 90
                and len(self.manager_mediator.get_own_army_dict[UnitID.PHOENIX]) < 8
            ):
                macro_plan.add(
                    SpawnController(
                        {UnitID.PHOENIX: {"proportion": 1.0, "priority": 0}}
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
            if self.can_expand:
                macro_plan.add(ExpansionController(to_count=100, max_pending=2))
            macro_plan.add(
                GasBuildingController(
                    to_count=self.gas_buildings_required,
                    max_pending=1 if self.ai.supply_workers < 60 else 3,
                )
            )
            add_production_at_bank: tuple = (300, 300)
            if self.deimos_mediator.get_enemy_rushed:
                add_production_at_bank = (150, 0)
            macro_plan.add(
                ProductionController(
                    self.deimos_mediator.get_army_comp,
                    base_location=self._main_building_location,
                    add_production_at_bank=add_production_at_bank,
                    alpha=0.7,
                )
            )

            self.ai.register_behavior(macro_plan)

    def _do_mining(self):
        gatherers: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.GATHERING
        )
        if (
            (
                self.manager_mediator.get_enemy_worker_rushed
                and len(gatherers) < 21
                and self.ai.time < 210.0
            )
            or len(gatherers) < 12
            or (
                self.ai.minerals < 100
                and self.ai.vespene > 300
                and self.ai.supply_used < 64
            )
        ):
            self._workers_per_gas = 0
        elif self.ai.vespene < 100:
            self._workers_per_gas = 3
        self.ai.register_behavior(Mining(workers_per_gas=self._workers_per_gas))

    def _check_building_location(self):
        if self.ai.time > 540.0 and self.ai.ready_townhalls:
            self._main_building_location = self.ai.ready_townhalls.furthest_to(
                self.ai.start_location
            ).position
