from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ares import ManagerMediator
from ares.managers.squad_manager import UnitSquad
from sc2.ids.ability_id import AbilityId
from sc2.units import Units

from bot.combat.base_combat import BaseCombat
from cython_extensions import cy_distance_to_squared

if TYPE_CHECKING:
    from ares import AresBot


@dataclass
class MapControlShades(BaseCombat):
    """Execute behavior for map control shades.

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

    def execute(self, units: Units, **kwargs) -> None:
        """Actually execute shade micro.

        Parameters
        ----------
        units : UnitSquad
            The squad we want to control.
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        grid : np.ndarray
        target_dict : Dict
        cancel_shades_dict: Dict
        """

        for unit in units:
            if unit.buff_duration_remain > 4 or unit.is_moving or (
                unit.order_target
                and cy_distance_to_squared(unit.order_target, unit.position) > 630.0
            ):
                continue
            unit(AbilityId.CANCEL_ADEPTSHADEPHASESHIFT)
