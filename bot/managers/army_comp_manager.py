from typing import TYPE_CHECKING, Any

from ares import ManagerMediator
from ares.managers.manager import Manager
from sc2.ids.unit_typeid import UnitTypeId as UnitID

from bot.consts import RequestType
from bot.managers.deimos_mediator import DeimosMediator

if TYPE_CHECKING:
    from ares import AresBot


class ArmyCompManager(Manager):
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
            RequestType.GET_ARMY_COMP: lambda kwargs: self._army_comp
        }

        self._army_comp: dict = self.stalker_immortal_comp

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
    def stalker_comp(self) -> dict:
        return {
            UnitID.STALKER: {"proportion": 1.0, "priority": 0},
        }

    @property
    def tempests_comp(self) -> dict:
        return {
            UnitID.TEMPEST: {"proportion": 1.0, "priority": 0},
        }

    @property
    def zealot_only(self) -> dict:
        return {
            UnitID.ZEALOT: {"proportion": 1.0, "priority": 0},
        }

    async def update(self, iteration: int) -> None:
        if self.manager_mediator.get_enemy_worker_rushed and self.ai.supply_used < 26:
            self._army_comp = self.zealot_only
        elif self.ai.build_order_runner.chosen_opening == "OneBaseTempests":
            self._army_comp = self.tempests_comp
        elif (
            len(self.manager_mediator.get_enemy_army_dict[UnitID.MARINE]) > 6
            and self.ai.supply_army < 32
        ):
            self._army_comp = self.stalker_comp
        elif len(self.manager_mediator.get_enemy_army_dict[UnitID.MUTALISK]) > 0:
            self._army_comp = self.stalker_immortal_phoenix_comp
        elif self.ai.supply_used > 114:
            self._army_comp = self.stalker_tempests_comp
        elif self.manager_mediator.get_enemy_ling_rushed and self.ai.supply_army < 20:
            self._army_comp = self.adept_only_comp
        elif self.deimos_mediator.get_enemy_rushed and self.ai.time < 330.0:
            self._army_comp = self.stalker_immortal_no_observer
        elif self.ai.build_order_runner.chosen_opening == "PhoenixEconomic":
            self._army_comp = self.stalker_immortal_phoenix_comp
        else:
            self._army_comp = self.stalker_immortal_comp
