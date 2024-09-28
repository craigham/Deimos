from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Callable

from sc2.unit import Unit

from bot.consts import RequestType

if TYPE_CHECKING:
    from ares.managers.manager import Manager


class IDeimosMediator(metaclass=ABCMeta):
    """
    The Mediator interface declares a method used by components to notify the
    mediator about various events. The Mediator may react to these events and
    pass the execution to other components (managers).
    """

    # each manager has a dict linking the request type to a callable action
    deimos_requests_dict: dict[RequestType, Callable]

    @abstractmethod
    def manager_request(
        self, receiver: str, request: RequestType, reason: str = None, **kwargs
    ) -> Any:
        """How requests will be structured.

        Parameters
        ----------
        receiver :
            The Manager the request is being sent to.
        request :
            The Manager that made the request
        reason :
            Why the Manager has made the request
        kwargs :
            If the ManagerRequest is calling a function, that function's keyword
            arguments go here.

        Returns
        -------
        Any

        """
        pass


class DeimosMediator(IDeimosMediator):
    def __init__(self) -> None:
        self.managers: dict[str, "Manager"] = {}

    def add_managers(self, managers: list["Manager"]) -> None:
        """Generate manager dictionary.

        Parameters
        ----------
        managers :
            List of all Managers capable of handling ManagerRequests.
        """
        for manager in managers:
            self.managers[str(type(manager).__name__)] = manager
            manager.deimos_mediator = self

    def manager_request(
        self, receiver: str, request: RequestType, reason: str = None, **kwargs
    ) -> Any:
        """Function to request information from a manager.

        Parameters
        ----------
        receiver :
            Manager receiving the request.
        request :
            Requested attribute/function call.
        reason :
            Why the request is being made.
        kwargs :
            Keyword arguments (if any) to be passed to the requested function.

        Returns
        -------
        Any :
            There are too many possible return types to list all of them.

        """
        return self.managers[receiver].manager_request(
            receiver, request, reason, **kwargs
        )

    @property
    def get_adept_to_phase(self) -> dict:
        return self.manager_request("AdeptManager", RequestType.GET_ADEPT_TO_PHASE)

    @property
    def get_army_comp(self) -> dict:
        return self.manager_request("ArmyCompManager", RequestType.GET_ARMY_COMP)

    @property
    def get_enemy_early_double_gas(self) -> list[Unit]:
        return self.manager_request(
            "ReconManager", RequestType.GET_ENEMY_EARLY_DOUBLE_GAS
        )

    @property
    def get_enemy_early_roach_warren(self) -> list[Unit]:
        return self.manager_request(
            "ReconManager", RequestType.GET_ENEMY_EARLY_ROACH_WARREN
        )

    @property
    def get_enemy_proxies(self) -> list[Unit]:
        return self.manager_request("ReconManager", RequestType.GET_ENEMY_PROXIES)

    @property
    def get_enemy_rushed(self) -> bool:
        return self.manager_request("ReconManager", RequestType.GET_ENEMY_RUSHED)

    @property
    def get_enemy_went_mass_ling(self) -> bool:
        return self.manager_request("ReconManager", RequestType.GET_WENT_MASS_LING)
