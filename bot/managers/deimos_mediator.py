from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional

from sc2.ids.unit_typeid import UnitTypeId as UnitID
from sc2.position import Point2

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
    phobos_requests_dict: dict[RequestType, Callable]

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
            manager.phobos_mediator = self

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

    def add_to_queue(self, **kwargs) -> None:
        self.manager_request("PriorityManager", RequestType.ADD_TO_QUEUE, **kwargs)

    @property
    def get_are_queues_empty(self) -> bool:
        return self.manager_request("PriorityManager", RequestType.GET_ARE_QUEUES_EMPTY)

    @property
    def get_army_comp(self) -> dict[UnitID, Any]:
        return self.manager_request("ArmyCompManager", RequestType.GET_ARMY_COMP)

    @property
    def get_attack_target(self) -> Point2:
        return self.manager_request("CombatManager", RequestType.GET_ATTACK_TARGET)

    @property
    def get_is_aggressive(self) -> bool:
        return self.manager_request("CombatManager", RequestType.GET_IS_AGGRESSIVE)

    def get_is_item_in_queue(self, **kwargs) -> bool:
        return self.manager_request(
            "PriorityManager", RequestType.GET_IS_ITEM_IN_QUEUE, **kwargs
        )

    @property
    def get_next_expansion_location(self) -> Optional[Point2]:
        return self.manager_request(
            "ExpansionManager", RequestType.GET_NEXT_EXPANSION_LOCATION
        )

    @property
    def get_rally_point(self) -> Point2:
        return self.manager_request("CombatManager", RequestType.GET_RALLY_POINT)

    @property
    def get_reaper_scout_finished(self) -> Point2:
        return self.manager_request(
            "ScoutManager", RequestType.GET_REAPER_SCOUT_FINISHED
        )

    @property
    def get_tank_to_new_position_dict(self) -> Point2:
        return self.manager_request(
            "LeapfrogManager", RequestType.GET_TANK_TO_NEW_POSITION_DICT
        )

    def request_scan(self, **kwargs) -> None:
        return self.manager_request(
            "OrbitalManager", RequestType.REQUEST_SCAN, **kwargs
        )
