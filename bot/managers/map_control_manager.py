from typing import TYPE_CHECKING

import numpy as np
from sc2.data import Race

from ares import ManagerMediator
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.units import Units

from bot.combat.base_unit import BaseUnit
from bot.combat.map_control_voidrays import MapControlVoidrays
from bot.consts import STEAL_FROM_ROLES, UnitRole
from bot.managers.deimos_mediator import DeimosMediator

if TYPE_CHECKING:
    from ares import AresBot


class MapControlManager(Manager):
    deimos_mediator: DeimosMediator

    map_control_voidrays: BaseUnit

    def __init__(
        self,
        ai: "AresBot",
        config: dict,
        mediator: ManagerMediator,
    ) -> None:
        """Handle Map Control activities.

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

    def initialise(self) -> None:
        self.map_control_voidrays: BaseUnit = MapControlVoidrays(
            self.ai, self.config, self.ai.mediator
        )

    async def update(self, iteration: int) -> None:
        if self.ai.enemy_race == Race.Zerg:
            self._handle_map_control_voids()
            # self._handle_map_control_adepts()

    def _handle_map_control_voids(self):
        grid: np.ndarray = self.manager_mediator.get_air_grid
        voids: Units = self.manager_mediator.get_units_from_roles(
            roles=STEAL_FROM_ROLES, unit_type=UnitID.VOIDRAY
        )
        for void in voids:
            self.manager_mediator.assign_role(tag=void.tag, role=UnitRole.MAP_CONTROL)
        voids: Units = self.manager_mediator.get_units_from_role(
            role=UnitRole.MAP_CONTROL, unit_type=UnitID.VOIDRAY
        )
        self.map_control_voidrays.execute(voids, grid=grid)
