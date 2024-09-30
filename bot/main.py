from typing import Optional

from sc2.data import Race

from ares import AresBot, Hub, ManagerMediator, UnitRole
from ares.managers.manager import Manager
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.unit import Unit
from sc2.units import Units

from bot.managers.adept_manager import AdeptManager
from bot.managers.army_comp_manager import ArmyCompManager
from bot.managers.combat_manager import CombatManager
from bot.managers.deimos_mediator import DeimosMediator
from bot.managers.macro_manager import MacroManager
from bot.managers.map_control_manager import MapControlManager
from bot.managers.nexus_manager import NexusManager
from bot.managers.oracle_manager import OracleManager
from bot.managers.phoenix_manager import PhoenixManager
from bot.managers.recon_manager import ReconManager
from bot.managers.scout_manager import ScoutManager
from bot.managers.worker_defence_manager import WorkerDefenceManager


class MyBot(AresBot):
    def __init__(self, game_step_override: Optional[int] = None):
        """Initiate custom bot

        Parameters
        ----------
        game_step_override :
            If provided, set the game_step to this value regardless of how it was
            specified elsewhere
        """
        super().__init__(game_step_override)
        self._deimos_mediator: DeimosMediator = DeimosMediator()
        self._starting_enemy_race: Race = Race.Protoss
        self._switched_opening_due_to_random: bool = False

    def register_managers(self) -> None:
        """
        Override the default `register_managers` in Ares, so we can
        add our own managers.
        """
        manager_mediator = ManagerMediator()

        additional_managers: list[Manager] = [
            MapControlManager(self, self.config, manager_mediator),
            AdeptManager(self, self.config, manager_mediator),
            ArmyCompManager(self, self.config, manager_mediator),
            CombatManager(self, self.config, manager_mediator),
            MacroManager(self, self.config, manager_mediator),
            NexusManager(self, self.config, manager_mediator),
            OracleManager(self, self.config, manager_mediator),
            PhoenixManager(self, self.config, manager_mediator),
            ReconManager(self, self.config, manager_mediator),
            ScoutManager(self, self.config, manager_mediator),
            WorkerDefenceManager(self, self.config, manager_mediator),
        ]
        self.manager_hub = Hub(
            self, self.config, manager_mediator, additional_managers=additional_managers
        )

        self._deimos_mediator.add_managers(additional_managers)

        self.manager_hub.init_managers()

        self._starting_enemy_race = self.enemy_race

    async def on_step(self, iteration: int) -> None:
        await super(MyBot, self).on_step(iteration)
        if not self.build_order_runner.build_completed:
            if (
                (
                    self._deimos_mediator.get_enemy_rushed
                    and self.build_order_runner.chosen_opening != "OneBaseTempests"
                    and not self.mediator.get_enemy_ravager_rush
                    and not self.mediator.get_enemy_roach_rushed
                )
                or self.minerals > 800
                or (
                    self.mediator.get_enemy_roach_rushed
                    and self.unit_pending(UnitID.VOIDRAY)
                )
                or (len(self.mediator.get_enemy_army_dict[UnitID.MARINE]) > 6)
                or (len(self.mediator.get_enemy_army_dict[UnitID.REAPER]) > 2)
            ):
                if self.mediator.get_enemy_roach_rushed:
                    for th in self.townhalls.not_ready:
                        self.mediator.cancel_structure(structure=th)
                if self.enemy_race == Race.Terran:
                    for sg in self.enemy_structures(UnitID.STARGATE):
                        self.mediator.cancel_structure(structure=sg)

                if not self._deimos_mediator.get_enemy_proxies:
                    worker_scouts: Units = self.mediator.get_units_from_role(
                        role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=self.worker_type
                    )
                    for scout in worker_scouts:
                        self.mediator.assign_role(
                            tag=scout.tag, role=UnitRole.GATHERING
                        )
                        scout.gather(self.mineral_field.closest_to(self.start_location))

                logger.info(f"{self.time_formatted}: Setting BO Completed")
                self.build_order_runner.set_build_completed()

        if (
            self._starting_enemy_race == Race.Random
            and self.enemy_race != Race.Random
            and not self._switched_opening_due_to_random
        ):
            switch_to: str = "PhoenixEconomic"
            if self.enemy_race == Race.Zerg:
                switch_to = "AdeptVoidray"
            elif self.enemy_race == Race.Protoss:
                switch_to = "AdeptOracle"
            self.build_order_runner.switch_opening(switch_to)
            await self.chat_send(f"Tag:Random_{self.enemy_race.name}")
            self._switched_opening_due_to_random = True

    async def on_unit_created(self, unit: Unit) -> None:
        await super(MyBot, self).on_unit_created(unit)

        # don't assign worker a role, ares does this already (GATHERING)
        if unit.type_id == UnitID.PROBE:
            return

        # assign everything else to defend by default
        # other managers can reassign as needed
        self.mediator.assign_role(tag=unit.tag, role=UnitRole.ATTACKING)

    """
    Can use `python-sc2` hooks as usual, but make a call the inherited method in the superclass
    Examples:
    """
    # async def on_start(self) -> None:
    #     await super(MyBot, self).on_start()
    #
    #     # on_start logic here ...
    #
    # async def on_end(self, game_result: Result) -> None:
    #     await super(MyBot, self).on_end(game_result)
    #
    #     # custom on_end logic here ...
    #
    # async def on_building_construction_complete(self, unit: Unit) -> None:
    #     await super(MyBot, self).on_building_construction_complete(unit)
    #
    #     # custom on_building_construction_complete logic here ...
    #
    # async def on_unit_created(self, unit: Unit) -> None:
    #     await super(MyBot, self).on_unit_created(unit)
    #
    #     # custom on_unit_created logic here ...
    #
    # async def on_unit_destroyed(self, unit_tag: int) -> None:
    #     await super(MyBot, self).on_unit_destroyed(unit_tag)
    #
    #     # custom on_unit_destroyed logic here ...
    #
    # async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float) -> None:
    #     await super(MyBot, self).on_unit_took_damage(unit, amount_damage_taken)
    #
    #     # custom on_unit_took_damage logic here ...
