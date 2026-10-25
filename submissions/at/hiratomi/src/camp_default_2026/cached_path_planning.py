"""Static-map shortest-path distances reused for the current source position."""

import heapq
from itertools import count

from adf_core_python.implement.module.algorithm.dijkstra_path_planning import (
    DijkstraPathPlanning,
)
from rcrscore.entities import EntityID


class CachedPathPlanning(DijkstraPathPlanning):
    """Keep one distance table per instance; movement paths use upstream Dijkstra.

    Like the upstream planner, graph weights are fixed at construction time.
    This planner does not model changing blockades. Replacing the graph requires
    invalidating the distance table with ``clear_distance_cache()``.
    """

    def clear_distance_cache(self) -> None:
        self._distance_source = None
        self._distance_table = {}

    def get_distance(self, from_entity_id: EntityID, to_entity_id: EntityID) -> float:
        if getattr(self, "_distance_source", None) != from_entity_id:
            self._distance_table = self._distances_from(from_entity_id)
            self._distance_source = from_entity_id
        return self._distance_table.get(to_entity_id, float("inf"))

    def _distances_from(self, source: EntityID) -> dict[EntityID, float]:
        if source not in self.graph:
            return {}
        distances = {source: 0.0}
        sequence = count()
        queue = [(0.0, next(sequence), source)]
        while queue:
            distance, _, current = heapq.heappop(queue)
            if distance > distances[current]:
                continue
            for neighbor, weight in self.graph.get(current, []):
                if neighbor not in self.graph:
                    continue
                candidate = distance + weight
                if candidate < distances.get(neighbor, float("inf")):
                    distances[neighbor] = candidate
                    heapq.heappush(queue, (candidate, next(sequence), neighbor))
        return distances
