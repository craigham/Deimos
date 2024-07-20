from typing import Optional

from ares import AresBot, Hub, ManagerMediator, UnitRole
from ares.behaviors.macro import (
    AutoSupply,
    MacroPlan,
    Mining,
    ProductionController,
    SpawnController,
)
from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.unit import Unit

from bot.managers.adept_harass_manager import AdeptHarassManager
from bot.managers.combat_manager import CombatManager
from bot.managers.oracle_manager import OracleManager
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

        self._army_comp: dict = self.stalker_immortal_comp

    @property
    def adept_only_comp(self) -> dict:
        return {
            UnitID.ADEPT: {"proportion": 1.0, "priority": 0},
        }

    @property
    def stalker_immortal_comp(self) -> dict:
        return {
            UnitID.OBSERVER: {"proportion": 0.01, "priority": 0},
            UnitID.IMMORTAL: {"proportion": 0.09, "priority": 1},
            UnitID.STALKER: {"proportion": 0.9, "priority": 2},
        }

    def register_managers(self) -> None:
        """
        Override the default `register_managers` in Ares, so we can
        add our own managers.
        """
        manager_mediator = ManagerMediator()
        self.manager_hub = Hub(
            self,
            self.config,
            manager_mediator,
            additional_managers=[
                AdeptHarassManager(self, self.config, manager_mediator),
                CombatManager(self, self.config, manager_mediator),
                OracleManager(self, self.config, manager_mediator),
                WorkerDefenceManager(self, self.config, manager_mediator),
            ],
        )

        self.manager_hub.init_managers()

    async def on_step(self, iteration: int) -> None:
        await super(MyBot, self).on_step(iteration)

        self.register_behavior(Mining())
        if self.build_order_runner.build_completed:
            if self.mediator.get_enemy_ling_rushed:
                self._army_comp = self.adept_only_comp
            else:
                self._army_comp = self.stalker_immortal_comp

            macro_plan: MacroPlan = MacroPlan()
            macro_plan.add(AutoSupply(self.start_location))
            macro_plan.add(
                ProductionController(
                    self._army_comp, base_location=self.start_location
                )
            )
            macro_plan.add(
                SpawnController(
                    self._army_comp, spawn_target=self.mediator.get_own_nat
                )
            )

            self.register_behavior(macro_plan)

        if not self.build_order_runner.build_completed and (
            self.mediator.get_enemy_ling_rushed
            or (self.mediator.get_enemy_marauder_rush and self.time < 150.0)
            or self.mediator.get_enemy_marine_rush
            or self.mediator.get_is_proxy_zealot
            or self.mediator.get_enemy_ravager_rush
            or self.mediator.get_enemy_went_marine_rush
            or self.mediator.get_enemy_four_gate
            or self.mediator.get_enemy_roach_rushed
            or self.mediator.get_enemy_worker_rushed
            # general check, no build should be banking this much
            or self.minerals > 750
        ):
            if self.mediator.get_enemy_roach_rushed:
                for th in self.townhalls.not_ready:
                    self.mediator.cancel_structure(structure=th)
            logger.info(f"{self.time_formatted}: Setting BO Completed")
            self.build_order_runner.set_build_completed()

    async def on_unit_created(self, unit: Unit) -> None:
        await super(MyBot, self).on_unit_created(unit)

        if unit.type_id in {UnitID.ORACLE}:
            self.mediator.assign_role(tag=unit.tag, role=UnitRole.HARASSING)
        elif unit.type_id == UnitID.ADEPT:
            self.mediator.assign_role(tag=unit.tag, role=UnitRole.CONTROL_GROUP_ONE)
        elif unit.type_id == UnitID.ADEPTPHASESHIFT:
            self.mediator.assign_role(tag=unit.tag, role=UnitRole.CONTROL_GROUP_TWO)

        # assign all other units to ATTACKING role by default
        elif unit.type_id != UnitID.PROBE:
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
