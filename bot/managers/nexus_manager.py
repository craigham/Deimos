from typing import TYPE_CHECKING

from ares import ManagerMediator
from ares.managers.manager import Manager
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId as UnitID

from bot.managers.deimos_mediator import DeimosMediator

if TYPE_CHECKING:
    from ares import AresBot


class NexusManager(Manager):
    deimos_mediator: DeimosMediator

    def __init__(
        self,
        ai: "AresBot",
        config: dict,
        mediator: ManagerMediator,
    ) -> None:
        """Handle Nexus abilities.

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

    async def update(self, iteration: int) -> None:
        self._handle_chrono_boosts()

    def _handle_chrono_boosts(self):
        if self.ai.build_order_runner.build_completed:
            if available_nexuses := [
                th for th in self.ai.townhalls if th.energy >= 50 and th.is_ready
            ]:
                if targets := [
                    s
                    for s in self.ai.structures
                    if s.is_ready
                    and not s.is_idle
                    and s.type_id
                    and not s.has_buff(BuffId.CHRONOBOOSTENERGYCOST)
                    and s.orders[0].progress < 0.4
                ]:
                    target = None
                    if self.ai.build_order_runner.chosen_opening == "OneBaseTempests":
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
