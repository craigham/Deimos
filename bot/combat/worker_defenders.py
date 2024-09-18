from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import numpy as np
from ares.behaviors.combat.individual import WorkerKiteBack
from ares.cache import property_cache_once_per_frame
from ares.consts import ALL_STRUCTURES, WORKER_TYPES, UnitTreeQueryType
from ares.managers.manager_mediator import ManagerMediator
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bot.combat.base_combat import BaseCombat
from cython_extensions import (
    cy_attack_ready,
    cy_center,
    cy_closest_to,
    cy_distance_to_squared,
    cy_in_attack_range,
    cy_pick_enemy_target,
    cy_sorted_by_distance_to,
)

if TYPE_CHECKING:
    from ares import AresBot


@dataclass
class WorkerDefenders(BaseCombat):
    """Execute behavior for mines and medivac in a mine drop.

    Called from `ScoutManager`

    Parameters
    ----------
    ai : AresBot
        Bot object that will be running the game
    config : Dict[Any, Any]
        Dictionary with the data from the configuration file
    mediator : ManagerMediator
        Used for getting information from managers in Ares.
    """

    ai: "AresBot"
    config: dict
    mediator: ManagerMediator
    set_up_worker_defence: bool = False

    @property_cache_once_per_frame
    def proxy_structures(self) -> list[Unit]:
        return [
            s
            for s in self.ai.enemy_structures
            if s.type_id
            in {
                UnitID.PYLON,
                UnitID.HATCHERY,
                UnitID.PHOTONCANNON,
                UnitID.COMMANDCENTER,
                UnitID.BUNKER,
            }
            and cy_distance_to_squared(s.position, self.ai.start_location) < 2304.0
        ]

    def execute(self, units: Units, **kwargs) -> None:
        """Execute the mine drop.

        Parameters
        ----------
        units : list[Unit]
            The units we want MedivacMineDrop to control.
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        medivac_tag_to_mine_tracker : dict[int, dict]
            Tracker detailing medivac tag to mine tags.
            And target for the mine drop.

        """
        if not units:
            return

        ground_near_workers: dict[int, Units] = self.mediator.get_units_in_range(
            start_points=units,
            distances=15,
            query_tree=UnitTreeQueryType.EnemyGround,
            return_as_dict=True,
        )
        grid: np.ndarray = self.mediator.get_ground_grid

        # stack workers up before fight commences
        if self.mediator.get_enemy_worker_rushed and not self.set_up_worker_defence:
            self._pre_worker_rush(units)
            return

        for worker in units:
            if worker.is_carrying_resource and self.ai.townhalls:
                worker.return_resource()
                continue

            near_ground: Units = ground_near_workers[worker.tag]

            # if enemy worker in range, target that if attack ready
            # but dont chase the worker
            enemy_workers_target: Optional[Unit] = None
            if enemy_workers := [u for u in near_ground if u.type_id in WORKER_TYPES]:
                if enemy_workers_in_range := cy_in_attack_range(worker, enemy_workers):
                    target: Unit = cy_pick_enemy_target(enemy_workers_in_range)
                    if cy_attack_ready(self.ai, worker, target):
                        enemy_workers_target = target

            if enemy_workers_target:
                worker.attack(enemy_workers_target)
            elif proxies := self.proxy_structures:
                worker.attack(cy_closest_to(worker.position, proxies))
            elif threats := [
                u
                for u in near_ground
                if u.type_id not in WORKER_TYPES and not u.is_structure
            ]:
                self.ai.register_behavior(
                    WorkerKiteBack(
                        unit=worker,
                        target=cy_closest_to(worker.position, threats),
                    )
                )
            elif near_ground:
                target: Unit = cy_closest_to(worker.position, near_ground)
                if target.type_id in ALL_STRUCTURES:
                    worker.attack(target)
                else:
                    self.ai.register_behavior(
                        WorkerKiteBack(
                            unit=worker,
                            target=cy_closest_to(worker.position, near_ground),
                        )
                    )
            elif enemy_near_base := self.mediator.get_main_ground_threats_near_townhall:
                worker.attack(Point2(cy_center(enemy_near_base)))

            elif mfs := self.ai.mineral_field:
                worker.gather(cy_closest_to(worker.position, mfs))

    def _pre_worker_rush(self, units: Units) -> None:
        mfs: list[Unit] = [
            mf
            for mf in self.ai.mineral_field
            if cy_distance_to_squared(mf.position, self.ai.start_location) < 150.0
        ]

        far_mineral_field: Unit = cy_sorted_by_distance_to(mfs, self.ai.start_location)[
            -1
        ]

        for unit in units:
            unit.gather(far_mineral_field)

        units_close_to_mf: list[Unit] = [
            u
            for u in units
            if cy_distance_to_squared(u.position, far_mineral_field.position) < 6.5
        ]

        if len(units_close_to_mf) > len(units) * 0.8:
            self.set_up_worker_defence = True
