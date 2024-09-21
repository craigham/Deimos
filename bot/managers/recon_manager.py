from typing import TYPE_CHECKING, Any

from ares import ManagerMediator
from ares.cache import property_cache_once_per_frame
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.unit import Unit

from bot.consts import RequestType
from bot.managers.deimos_mediator import DeimosMediator
from cython_extensions import cy_distance_to_squared

if TYPE_CHECKING:
    from ares import AresBot


class ReconManager(Manager):
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

        self.deimos_requests_dict = {
            RequestType.GET_ENEMY_EARLY_ROACH_WARREN: lambda kwargs: self._enemy_early_roach_warren,
            RequestType.GET_ENEMY_PROXIES: lambda kwargs: self.enemy_proxies,
            RequestType.GET_ENEMY_RUSHED: lambda kwargs: self._enemy_rushed,
        }

        self._enemy_rushed: bool = False
        self._enemy_early_roach_warren: bool = False

    def manager_request(
        self,
        receiver: str,
        request: RequestType,
        reason: str = None,
        **kwargs,
    ) -> Any:
        """Fetch information from this Manager so another Manager can use it.

        Parameters
        ----------
        receiver :
            This Manager.
        request :
            What kind of request is being made
        reason :
            Why the reason is being made
        kwargs :
            Additional keyword args if needed for the specific request, as determined
            by the function signature (if appropriate)

        Returns
        -------
        Optional[Union[Dict, DefaultDict, Coroutine[Any, Any, bool]]] :
            Everything that could possibly be returned from the Manager fits in there

        """
        return self.deimos_requests_dict[request](kwargs)

    @property
    def did_enemy_rush(self) -> bool:
        return (
            self.manager_mediator.get_enemy_ling_rushed
            or self.manager_mediator.get_enemy_marauder_rush
            or self.manager_mediator.get_enemy_marine_rush
            or self.manager_mediator.get_is_proxy_zealot
            or self.manager_mediator.get_enemy_ravager_rush
            or self.manager_mediator.get_enemy_went_marine_rush
            or self.manager_mediator.get_enemy_four_gate
            or self.manager_mediator.get_enemy_roach_rushed
            or self.manager_mediator.get_enemy_worker_rushed
            or (
                len(self.manager_mediator.get_enemy_army_dict[UnitID.MARINE]) > 6
                and self.ai.time < 300.0
            )
            or self._enemy_early_roach_warren
        )

    @property_cache_once_per_frame
    def enemy_proxies(self) -> list[Unit]:
        return [
            s
            for s in self.ai.enemy_structures
            if cy_distance_to_squared(s.position, self.manager_mediator.get_own_nat)
            < 4900.0
        ]

    async def update(self, iteration: int) -> None:
        if not self._enemy_rushed:
            self._enemy_rushed = self.did_enemy_rush

        if not self._enemy_early_roach_warren and self.ai.time < 110.0:
            if self.ai.enemy_structures(UnitID.ROACHWARREN):
                self._enemy_early_roach_warren = True
