from typing import Optional

from cython_extensions import cy_distance_to_squared, cy_closest_to
from sc2.ids.buff_id import BuffId

from ares import AresBot, Hub, ManagerMediator, UnitRole
from ares.behaviors.macro import (
    AutoSupply,
    MacroPlan,
    Mining,
    ProductionController,
    SpawnController,
)

from loguru import logger
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.unit import Unit
from sc2.units import Units

from ares.consts import GAS_BUILDINGS, UnitTreeQueryType, WORKER_TYPES, ALL_STRUCTURES
from bot.managers.adept_harass_manager import AdeptHarassManager
from bot.managers.combat_manager import CombatManager
from bot.managers.oracle_manager import OracleManager
from bot.managers.phoenix_manager import PhoenixManager
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
        self._enemy_rushed: bool = False

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

    @property
    def stalker_immortal_no_observer(self) -> dict:
        return {
            UnitID.IMMORTAL: {"proportion": 0.1, "priority": 1},
            UnitID.STALKER: {"proportion": 0.9, "priority": 0},
        }

    @property
    def stalker_immortal_phoenix_comp(self) -> dict:
        return {
            UnitID.OBSERVER: {"proportion": 0.01, "priority": 2},
            UnitID.IMMORTAL: {"proportion": 0.1, "priority": 1},
            UnitID.STALKER: {"proportion": 0.65, "priority": 3},
            UnitID.PHOENIX: {"proportion": 0.24, "priority": 0},
        }

    @property
    def stalker_tempests_comp(self) -> dict:
        return {
            UnitID.STALKER: {"proportion": 0.75, "priority": 1},
            UnitID.TEMPEST: {"proportion": 0.25, "priority": 0},
        }

    @property
    def tempests_comp(self) -> dict:
        return {
            UnitID.TEMPEST: {"proportion": 1.0, "priority": 0},
        }

    @property
    def enemy_rushed(self) -> bool:
        # TODO: engineer this to make it available to other classes
        #   Currently replicated in combat manager
        return (
            self.mediator.get_enemy_ling_rushed
            or self.mediator.get_enemy_marauder_rush
            or self.mediator.get_enemy_marine_rush
            or self.mediator.get_is_proxy_zealot
            or self.mediator.get_enemy_ravager_rush
            or self.mediator.get_enemy_went_marine_rush
            or self.mediator.get_enemy_four_gate
            or self.mediator.get_enemy_roach_rushed
            or self.mediator.get_enemy_worker_rushed
        )

    @property
    def proxies(self) -> list[Unit]:
        return [
            s
            for s in self.enemy_structures
            if cy_distance_to_squared(s.position, self.mediator.get_own_nat) < 4900.0
        ]

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
                PhoenixManager(self, self.config, manager_mediator),
                WorkerDefenceManager(self, self.config, manager_mediator),
            ],
        )

        self.manager_hub.init_managers()

    async def on_step(self, iteration: int) -> None:
        await super(MyBot, self).on_step(iteration)

        self.register_behavior(Mining())

        self._probe_proxy_denier()

        if self.build_order_runner.build_completed:
            # TODO: Make army comp manager and smarten this up
            if self.build_order_runner.chosen_opening == "OneBaseTempests":
                self._army_comp = self.tempests_comp
            elif self.supply_used > 114:
                self._army_comp = self.stalker_tempests_comp
            elif self.mediator.get_enemy_ling_rushed and self.time < 270.0:
                self._army_comp = self.adept_only_comp
            elif self._enemy_rushed and self.time < 330.0:
                self._army_comp = self.stalker_immortal_no_observer
            elif self.build_order_runner.chosen_opening == "PhoenixEconomic":
                self._army_comp = self.stalker_immortal_phoenix_comp
            else:
                self._army_comp = self.stalker_immortal_comp

            macro_plan: MacroPlan = MacroPlan()
            macro_plan.add(AutoSupply(self.start_location))
            macro_plan.add(
                ProductionController(self._army_comp, base_location=self.start_location)
            )
            macro_plan.add(
                SpawnController(
                    self._army_comp,
                    spawn_target=self.mediator.get_own_nat,
                    freeflow_mode=self.minerals > 500 and self.vespene > 500,
                    ignore_proportions_below_unit_count=4,
                )
            )

            self.register_behavior(macro_plan)

        if (
            not self.build_order_runner.build_completed
            and self.enemy_rushed
            and self.build_order_runner.chosen_opening != "OneBaseTempests"
        ):
            self._enemy_rushed = True
            if self.mediator.get_enemy_roach_rushed:
                for th in self.townhalls.not_ready:
                    self.mediator.cancel_structure(structure=th)

            if not self.proxies:
                worker_scouts: Units = self.mediator.get_units_from_role(
                    role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=self.worker_type
                )
                for scout in worker_scouts:
                    # issue custom commands
                    self.mediator.assign_role(tag=scout.tag, role=UnitRole.GATHERING)
                    scout.gather(self.mineral_field.closest_to(self.start_location))

            logger.info(f"{self.time_formatted}: Setting BO Completed")
            self.build_order_runner.set_build_completed()

        if self.build_order_runner.build_completed:
            max_probes: int = min(66, 22 * len(self.townhalls))
            if (
                self.can_afford(UnitID.PROBE)
                and self.townhalls.idle
                and self.supply_workers < max_probes
            ):
                self.train(UnitID.PROBE)

            if available_nexuses := [
                th for th in self.townhalls if th.energy >= 50 and th.is_ready
            ]:
                if targets := [
                    s
                    for s in self.structures
                    if s.is_ready
                    and not s.is_idle
                    and s.type_id
                    and not s.has_buff(BuffId.CHRONOBOOSTENERGYCOST)
                    and s.orders[0].progress < 0.4
                ]:
                    target = None
                    if self.build_order_runner.chosen_opening == "OneBaseTempests":
                        for t in targets:
                            if t.type_id == UnitID.STARGATE:
                                target = t
                                break
                    else:
                        target = targets[0]

                    if target:
                        available_nexuses[0](
                            AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, target
                        )

            num_gas: int = (
                len(self.gas_buildings)
                + self.mediator.get_building_counter[UnitID.ASSIMILATOR]
            )

            if self.supply_workers > 20:
                gas_required: int
                if self.supply_workers >= 48:
                    gas_required = 6
                else:
                    gas_required = 3
                if self.minerals > 1000:
                    gas_required = 60
                elif self.minerals > 450:
                    gas_required = 8
                elif self.minerals > 250:
                    gas_required = 7
                max_pending: int = 1 if self.supply_workers < 60 else 3
                if (
                    num_gas < gas_required
                    and self.mediator.get_building_counter[UnitID.ASSIMILATOR]
                    < max_pending
                    and self.minerals > 35
                ):
                    self._add_gas()

    def _add_gas(self):
        existing_gas_buildings: Units = self.structures(GAS_BUILDINGS)
        if available_geysers := self.vespene_geyser.filter(
            lambda g: not existing_gas_buildings.closer_than(5.0, g)
            and self.townhalls.closer_than(12.0, g)
            and [
                th
                for th in self.townhalls
                if th.build_progress > 0.92
                and cy_distance_to_squared(th.position, g.position) < 144.0
            ]
        ):
            if worker := self.mediator.select_worker(
                target_position=self.start_location, force_close=True
            ):
                self.mediator.build_with_specific_worker(
                    worker=worker,
                    structure_type=UnitID.ASSIMILATOR,
                    pos=available_geysers[0],
                )

    async def on_unit_created(self, unit: Unit) -> None:
        await super(MyBot, self).on_unit_created(unit)

        type_id: UnitID = unit.type_id
        # don't assign worker a role, ares does this already
        if type_id == UnitID.PROBE:
            return

        role: UnitRole
        match type_id:
            case UnitID.ADEPT:
                if self.mediator.get_enemy_ling_rushed:
                    role = UnitRole.ATTACKING
                else:
                    role = UnitRole.CONTROL_GROUP_ONE
            case UnitID.ADEPTPHASESHIFT:
                role = UnitRole.CONTROL_GROUP_TWO
            case UnitID.ORACLE:
                role = UnitRole.HARASSING_ORACLE
            case UnitID.PHOENIX:
                role = UnitRole.HARASSING_PHOENIX
            case UnitID.VOIDRAY:
                if self.supply_used < 66:
                    role = UnitRole.DEFENDING
                else:
                    role = UnitRole.ATTACKI
            case _:
                role = UnitRole.ATTACKING

        self.mediator.assign_role(tag=unit.tag, role=role)

    def _probe_proxy_denier(self):
        if self.proxies:
            worker_scouts: Units = self.mediator.get_units_from_role(
                role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=self.worker_type
            )
            for scout in worker_scouts:
                self.mediator.assign_role(tag=scout.tag, role=UnitRole.SCOUTING)

        if probes := self.mediator.get_units_from_role(
            role=UnitRole.SCOUTING, unit_type=UnitID.PROBE
        ):
            ground_near_workers: dict[int, Units] = self.mediator.get_units_in_range(
                start_points=probes,
                distances=15,
                query_tree=UnitTreeQueryType.EnemyGround,
                return_as_dict=True,
            )
            for probe in probes:
                enemy_near_worker: Units = ground_near_workers[probe.tag]
                if probe.shield_percentage < 0.1:
                    self.mediator.assign_role(tag=probe.tag, role=UnitRole.GATHERING)
                elif enemy_workers := [
                    u
                    for u in enemy_near_worker
                    if u.type_id in WORKER_TYPES
                    and cy_distance_to_squared(u.position, self.mediator.get_enemy_nat)
                    > 2600.0
                ]:
                    probe.attack(cy_closest_to(probe.position, enemy_workers))
                    continue

                elif structures := [
                    u
                    for u in enemy_near_worker
                    if u.type_id in ALL_STRUCTURES
                    and cy_distance_to_squared(u.position, self.mediator.get_enemy_nat)
                    > 1600.0
                ]:
                    probe.attack(cy_closest_to(probe.position, structures))

                else:
                    self.mediator.assign_role(tag=probe.tag, role=UnitRole.GATHERING)

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
