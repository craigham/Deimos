from dataclasses import dataclass
from itertools import cycle
from typing import TYPE_CHECKING

import numpy as np
from ares import ManagerMediator
from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import AttackTarget, UseAbility
from map_analyzer import MapData
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from src.ares.consts import UnitTreeQueryType

from bot.combat.base_combat import BaseCombat
from cython_extensions import (
    cy_center,
    cy_closest_to,
    cy_distance_to_squared,
    cy_pick_enemy_target,
)

if TYPE_CHECKING:
    from ares import AresBot


@dataclass
class MapControlVoidrays(BaseCombat):
    """Execute behavior for map control voidrays.

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
    current_ol_spot_target = None
    VOID_RANGE: float = 6.0

    def __post_init__(self) -> None:
        self.ol_spot_generator = None
        self._create_ol_spot_generator()
        self.current_ol_spot_target = next(self.ol_spot_generator)

    def execute(self, units: Units, **kwargs) -> None:
        """Actually execute defensive void control.

        Parameters
        ----------
        units : Units
            The voids we want to control.
        **kwargs :
            See below.

        Keyword Arguments
        -----------------
        grid : np.ndarray
        """

        if self.ai.is_visible(self.current_ol_spot_target):
            self.current_ol_spot_target = next(self.ol_spot_generator)
        grid: np.ndarray = kwargs["grid"]
        avoidance_grid: np.ndarray = self.mediator.get_air_avoidance_grid
        enemy_ground_threats: Units = (
            self.mediator.get_main_ground_threats_near_townhall
        )
        enemy_air_threats: Units = self.mediator.get_main_air_threats_near_townhall
        everything_near_voids: dict[int, Units] = self.mediator.get_units_in_range(
            start_points=units,
            distances=12.0,
            query_tree=UnitTreeQueryType.AllEnemy,
            return_as_dict=True,
        )
        enemy_near_spawn: list[Unit] = [
            u
            for u in self.ai.all_enemy_units
            if cy_distance_to_squared(self.ai.start_location, u.position) < 3600.0
        ]

        for unit in units:
            unit_tag: int = unit.tag
            close_enemy: Units = everything_near_voids[unit_tag].filter(
                lambda u: not u.is_memory
            )
            flying: list[Unit] = [u for u in close_enemy if u.is_flying]

            maneuver: CombatManeuver = CombatManeuver()

            if close_enemy:
                # dangerous effects etc, aggressively move to enemy
                if not self.mediator.is_position_safe(
                    grid=avoidance_grid, position=unit.position
                ):
                    target: Unit = cy_pick_enemy_target(close_enemy)
                    maneuver.add(UseAbility(AbilityId.MOVE_MOVE, unit, target.position))
                elif flying_in_attack_range := [
                    u
                    for u in flying
                    if cy_distance_to_squared(unit.position, u.position)
                    < 36.0 + unit.radius + u.radius
                ]:
                    target: Unit = cy_pick_enemy_target(flying_in_attack_range)
                    maneuver.add(AttackTarget(unit=unit, target=target))
                elif in_attack_range := [
                    u
                    for u in close_enemy
                    if cy_distance_to_squared(unit.position, u.position)
                    < 36.0 + unit.radius + u.radius
                ]:
                    armoured: list[Unit] = [u for u in in_attack_range if u.is_armored]
                    if armoured:
                        maneuver.add(
                            UseAbility(
                                AbilityId.EFFECT_VOIDRAYPRISMATICALIGNMENT, unit, None
                            )
                        )
                        target: Unit = cy_pick_enemy_target(armoured)
                        maneuver.add(AttackTarget(unit=unit, target=target))
                    else:
                        target: Unit = cy_pick_enemy_target(in_attack_range)
                        maneuver.add(AttackTarget(unit=unit, target=target))
                else:
                    target: Unit = cy_pick_enemy_target(close_enemy)
                    maneuver.add(
                        UseAbility(
                            AbilityId.ATTACK_ATTACK,
                            unit,
                            target,
                        )
                    )

            move_to: Point2 = self.current_ol_spot_target
            if self.ai.time > 295.0:
                move_to = self.ai.enemy_start_locations[0]
            elif enemy_near_spawn:
                move_to = cy_closest_to(unit.position, enemy_near_spawn).position
            elif enemy_ground_threats:
                move_to = cy_closest_to(unit.position, enemy_ground_threats).position
            elif enemy_air_threats:
                move_to = cy_closest_to(unit.position, enemy_air_threats).position

            maneuver.add(
                UseAbility(
                    AbilityId.ATTACK_ATTACK,
                    unit,
                    move_to,
                )
            )

            self.ai.register_behavior(maneuver)

    def _create_ol_spot_generator(self):
        map_data: MapData = self.mediator.get_map_data_object
        high_ground_spots = [
            Point2(tuple_spot) for tuple_spot in map_data.overlord_spots
        ]
        len_spots = len(high_ground_spots)
        distances = np.empty(len_spots)
        for i in range(len_spots):
            distances[i] = cy_distance_to_squared(
                high_ground_spots[i].position,
                self.ai.start_location.towards(self.ai.game_info.map_center, 15.0),
            )

        indices = distances.argsort()

        spots = [
            high_ground_spots[j]
            for j in indices
            if cy_distance_to_squared(
                high_ground_spots[j], self.ai.enemy_start_locations[0]
            )
            > 4900
        ]

        self.ol_spot_generator = cycle(spots)
