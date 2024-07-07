from typing import TYPE_CHECKING, Protocol

import numpy as np
from ares.behaviors.combat.individual import KeepUnitSafe
from ares.managers.manager_mediator import ManagerMediator
from ares.managers.squad_manager import UnitSquad
from sc2.unit import Unit

if TYPE_CHECKING:
    from ares import AresBot


class BaseSquadCombat(Protocol):
    """Basic interface that all combat classes should follow.

    Parameters
    ----------
    ai : AresBot
        Bot object that will be running the game
    config : Dict[Any, Any]
        Dictionary with the data from the configuration file
    mediator : ManagerMediator         u
        Used for getting information from managers in Ares.
    """

    ai: "AresBot"
    config: dict
    mediator: ManagerMediator

    def execute(self, squad: UnitSquad, **kwargs) -> None:
        """Execute the implemented behavior.

        This should be called every step.

        Parameters
        ----------
        squad :
            The UnitSquad these units are part of.
        **kwargs :
            See combat subclasses docstrings for supported kwargs.

        """
        ...

    def _avoid_danger_and_return_safe(
        self, grid: np.ndarray, units: list[Unit]
    ) -> list[Unit]:
        return [
            u
            for u in units
            if not KeepUnitSafe(u, grid).execute(self.ai, self.config, self.mediator)
        ]
