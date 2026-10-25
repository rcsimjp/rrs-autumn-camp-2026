# from typing import Optional, cast

# import random

# from rcrscore.entities import Building, Entity, EntityID, Refuge

# from adf_core_python.core.agent.communication.message_manager import MessageManager
# from adf_core_python.core.agent.develop.develop_data import DevelopData
# from adf_core_python.core.agent.info.agent_info import AgentInfo
# from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
# from adf_core_python.core.agent.info.world_info import WorldInfo
# from adf_core_python.core.agent.module.module_manager import ModuleManager
# from adf_core_python.core.component.module.algorithm.clustering import Clustering
# from adf_core_python.core.component.module.algorithm.path_planning import PathPlanning
# from adf_core_python.core.component.module.complex.search import Search
# from adf_core_python.core.logger.logger import get_agent_logger


# class SampleSearch(Search):
#   def __init__(
#     self,
#     agent_info: AgentInfo,
#     world_info: WorldInfo,
#     scenario_info: ScenarioInfo,
#     module_manager: ModuleManager,
#     develop_data: DevelopData,
#   ) -> None:
#     super().__init__(
#       agent_info, world_info, scenario_info, module_manager, develop_data
#     )

#     self._unreached_building_ids: set[EntityID] = set()
#     self._result: Optional[EntityID] = None

#     # 再探索開始時に最遠の建物を選ぶためのフラグ
#     self._is_research_start: bool = False

#     self._clustering: Clustering = cast(
#       Clustering,
#       module_manager.get_module(
#         "myteam.Search.Clustering",
#         "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
#       ),
#     )

#     self._path_planning: PathPlanning = cast(
#       PathPlanning,
#       module_manager.get_module(
#         "myteam.Search.PathPlanning",
#         "src.camp_default_2026.cached_path_planning.CachedPathPlanning",
#       ),
#     )

#     self._logger = get_agent_logger(
#       f"{self.__class__.__module__}.{self.__class__.__qualname__}",
#       self._agent_info,
#     )

#     self.register_sub_module(self._clustering)
#     self.register_sub_module(self._path_planning)

#   def update_info(self, message_manager: MessageManager) -> Search:
#     super().update_info(message_manager)

#     if self.get_count_update_info() > 1:
#       return self

#     searched_building_id = self._agent_info.get_position_entity_id()

#     if searched_building_id is not None:
#       self._unreached_building_ids.discard(searched_building_id)

#     if len(self._unreached_building_ids) == 0:
#       self._unreached_building_ids = self._get_search_targets()

#       # 再探索開始時、現在位置の建物を直ちに再選択しない
#       if searched_building_id is not None:
#         self._unreached_building_ids.discard(searched_building_id)

#       # 再探索開始を記録
#       self._is_research_start = True

#     return self

#   # def calculate(self) -> Search:
#   #   position = self._agent_info.get_position_entity_id()
#   #   if position is None:
#   #     self._result = None
#   #     return self

#   #   selected_building_id: Optional[EntityID] = None

#   #   if self._is_research_start:
#   #     # 再探索開始時は最も遠い建物を選ぶ
#   #     farthest_distance = float("-inf")

#   #     for building_id in self._unreached_building_ids:
#   #       distance = self._path_planning.get_distance(position, building_id)

#   #       if distance > farthest_distance:
#   #         selected_building_id = building_id
#   #         farthest_distance = distance

#   #     # 最遠の建物を選ぶ処理は今回限り
#   #     self._is_research_start = False

#   #   else:
#   #     # 通常時は最も近い建物を選ぶ
#   #     nearest_distance = float("inf")

#   #     for building_id in self._unreached_building_ids:
#   #       distance = self._path_planning.get_distance(position, building_id)

#   #       if distance < nearest_distance:
#   #         selected_building_id = building_id
#   #         nearest_distance = distance

#   #   self._result = selected_building_id
#   #   return self


#   def calculate(self) -> Search:
#     position = self._agent_info.get_position_entity_id()
#     if position is None:
#       self._result = None
#       return self

#     selected_building_id: Optional[EntityID] = None

#     if self._is_research_start:
#       # 再探索開始時はランダムに建物を選ぶ
#       if self._unreached_building_ids:
#         selected_building_id = random.choice(
#           list(self._unreached_building_ids)
#         )

#       # ランダム選択は今回限り
#       self._is_research_start = False

#     else:
#       # 通常時は最も近い建物を選ぶ
#       nearest_distance = float("inf")

#       for building_id in self._unreached_building_ids:
#         distance = self._path_planning.get_distance(
#           position, building_id
#         )

#         if distance < nearest_distance:
#           selected_building_id = building_id
#           nearest_distance = distance

#     self._result = selected_building_id
#     return self


#   def get_target_entity_id(self) -> Optional[EntityID]:
#     return self._result

#   def _get_search_targets(self) -> set[EntityID]:
#     cluster_index: int = self._clustering.get_cluster_index(
#       self._agent_info.get_entity_id()
#     )

#     cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
#       cluster_index
#     )

#     building_entity_ids: list[EntityID] = [
#       entity.get_entity_id()
#       for entity in cluster_entities
#       if isinstance(entity, Building) and not isinstance(entity, Refuge)
#     ]

#     return set(building_entity_ids)


# this 0.212
import random
from typing import Optional, cast

from rcrscore.entities import Building, Entity, EntityID, Refuge

from adf_core_python.core.agent.communication.message_manager import MessageManager
from adf_core_python.core.agent.develop.develop_data import DevelopData
from adf_core_python.core.agent.info.agent_info import AgentInfo
from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
from adf_core_python.core.agent.info.world_info import WorldInfo
from adf_core_python.core.agent.module.module_manager import ModuleManager
from adf_core_python.core.component.module.algorithm.clustering import Clustering
from adf_core_python.core.component.module.algorithm.path_planning import PathPlanning
from adf_core_python.core.component.module.complex.search import Search
from adf_core_python.core.logger.logger import get_agent_logger


class SampleSearch(Search):
  def __init__(
    self,
    agent_info: AgentInfo,
    world_info: WorldInfo,
    scenario_info: ScenarioInfo,
    module_manager: ModuleManager,
    develop_data: DevelopData,
  ) -> None:
    super().__init__(
      agent_info, world_info, scenario_info, module_manager, develop_data
    )

    self._unreached_building_ids: set[EntityID] = set()
    self._result: Optional[EntityID] = None

    self._clustering: Clustering = cast(
      Clustering,
      module_manager.get_module(
        "tteam.Search.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )

    self._path_planning: PathPlanning = cast(
      PathPlanning,
      module_manager.get_module(
        "tteam.Search.PathPlanning",
        "src.camp_default_2026.cached_path_planning.CachedPathPlanning",
      ),
    )

    self._logger = get_agent_logger(
      f"{self.__class__.__module__}.{self.__class__.__qualname__}",
      self._agent_info,
    )

    self.register_sub_module(self._clustering)
    self.register_sub_module(self._path_planning)

  def update_info(self, message_manager: MessageManager) -> Search:
    super().update_info(message_manager)

    if not self._unreached_building_ids:
        self._unreached_building_ids = self._get_search_targets()

    searched_building_id = self._agent_info.get_position_entity_id()
    if searched_building_id is not None:
        self._unreached_building_ids.discard(searched_building_id)

    return self

  def calculate(self) -> Search:
    position = self._agent_info.get_position_entity_id()

    # 既にターゲットが存在し、かつまだその建物に到着していない場合はターゲットを維持する
    if self._result is not None and position != self._result:
        if self._result in self._unreached_building_ids:
            return self

    # 到着した、またはターゲットが未設定の場合の新しいターゲット選択
    if not self._unreached_building_ids:
        self._unreached_building_ids = self._get_search_targets()

    if position is not None and position in self._unreached_building_ids:
        self._unreached_building_ids.discard(position)

    if not self._unreached_building_ids:
        self._unreached_building_ids = self._get_search_targets()
        if not self._unreached_building_ids:
            self._result = None
            return self

    # 未探索の建物からランダムに1つ選択する
    self._result = random.choice(list(self._unreached_building_ids))
    return self

  def get_target_entity_id(self) -> Optional[EntityID]:
    return self._result

  def _get_search_targets(self) -> set[EntityID]:
    cluster_index: int = self._clustering.get_cluster_index(
      self._agent_info.get_entity_id()
    )
    cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
      cluster_index
    )
    building_entity_ids: list[EntityID] = [
      entity.get_entity_id()
      for entity in cluster_entities
      if isinstance(entity, Building) and not isinstance(entity, Refuge)
    ]

    return set(building_entity_ids)

# random2
# import random
# from typing import Optional, cast

# from rcrscore.entities import Building, Entity, EntityID, Refuge

# from adf_core_python.core.agent.communication.message_manager import MessageManager
# from adf_core_python.core.agent.develop.develop_data import DevelopData
# from adf_core_python.core.agent.info.agent_info import AgentInfo
# from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
# from adf_core_python.core.agent.info.world_info import WorldInfo
# from adf_core_python.core.agent.module.module_manager import ModuleManager
# from adf_core_python.core.component.module.algorithm.clustering import Clustering
# from adf_core_python.core.component.module.algorithm.path_planning import PathPlanning
# from adf_core_python.core.component.module.complex.search import Search
# from adf_core_python.core.logger.logger import get_agent_logger


# class SampleSearch(Search):
#   def __init__(
#     self,
#     agent_info: AgentInfo,
#     world_info: WorldInfo,
#     scenario_info: ScenarioInfo,
#     module_manager: ModuleManager,
#     develop_data: DevelopData,
#   ) -> None:
#     super().__init__(
#       agent_info, world_info, scenario_info, module_manager, develop_data
#     )

#     self._unreached_building_ids: set[EntityID] = set()
#     self._result: Optional[EntityID] = None

#     # 探索モード管理用変数
#     self._target_type: str = "RANDOM"  # "RANDOM" または "GREEDY"
#     self._greedy_count: int = 0        # 貪欲法で探索した回数

#     self._clustering: Clustering = cast(
#       Clustering,
#       module_manager.get_module(
#         "myteam.Search.Clustering",
#         "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
#       ),
#     )

#     self._path_planning: PathPlanning = cast(
#       PathPlanning,
#       module_manager.get_module(
#         "myteam.Search.PathPlanning",
#         "src.camp_default_2026.cached_path_planning.CachedPathPlanning",
#       ),
#     )

#     self._logger = get_agent_logger(
#       f"{self.__class__.__module__}.{self.__class__.__qualname__}",
#       self._agent_info,
#     )

#     self.register_sub_module(self._clustering)
#     self.register_sub_module(self._path_planning)

#   def update_info(self, message_manager: MessageManager) -> Search:
#     super().update_info(message_manager)

#     if not self._unreached_building_ids:
#         self._unreached_building_ids = self._get_search_targets()

#     searched_building_id = self._agent_info.get_position_entity_id()
#     if searched_building_id is not None:
#         self._unreached_building_ids.discard(searched_building_id)

#     return self

#   def calculate(self) -> Search:
#     position = self._agent_info.get_position_entity_id()

#     # まだターゲットに到着していない場合は、移動しきるためにターゲットを維持する
#     if self._result is not None and position != self._result:
#         if self._result in self._unreached_building_ids:
#             return self

#     if position is not None and position in self._unreached_building_ids:
#         self._unreached_building_ids.discard(position)

#     if not self._unreached_building_ids:
#         self._unreached_building_ids = self._get_search_targets()
#         if not self._unreached_building_ids:
#             self._result = None
#             return self

#     # 初回（ターゲット未設定）の場合
#     if self._result is None:
#         self._result = random.choice(list(self._unreached_building_ids))
#         self._target_type = "RANDOM"
#         self._greedy_count = 0
#         return self

#     # ランダムな移動先に到着した場合、ここを起点として貪欲法モードに切り替える
#     if self._target_type == "RANDOM":
#         self._target_type = "GREEDY"
#         self._greedy_count = 0

#     # 貪欲法モードの処理
#     if self._target_type == "GREEDY":
#         if position is None:
#             self._result = random.choice(list(self._unreached_building_ids))
#             self._target_type = "RANDOM"
#             return self

#         # 最も近い未探索の建物を選択する（貪欲法）
#         nearest_building_id: Optional[EntityID] = None
#         nearest_distance = float("inf")

#         for building_id in self._unreached_building_ids:
#             distance = self._path_planning.get_distance(position, building_id)
#             if distance < nearest_distance:
#                 nearest_building_id = building_id
#                 nearest_distance = distance

#         if nearest_building_id is not None:
#             self._result = nearest_building_id
#             self._greedy_count += 1
#         else:
#             self._result = random.choice(list(self._unreached_building_ids))
#             self._target_type = "RANDOM"
#             self._greedy_count = 0
#             return self

#         # 6回連続で貪欲法を行ったら、再びランダム移動モードに戻す
#         if self._greedy_count >= 6:
#             self._result = random.choice(list(self._unreached_building_ids))
#             self._target_type = "RANDOM"
#             self._greedy_count = 0

#     return self

#   def get_target_entity_id(self) -> Optional[EntityID]:
#     return self._result

#   def _get_search_targets(self) -> set[EntityID]:
#     cluster_index: int = self._clustering.get_cluster_index(
#       self._agent_info.get_entity_id()
#     )
#     cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
#       cluster_index
#     )
#     building_entity_ids: list[EntityID] = [
#       entity.get_entity_id()
#       for entity in cluster_entities
#       if isinstance(entity, Building) and not isinstance(entity, Refuge)
#     ]

#     return set(building_entity_ids)

# fb sticky 0.192
# from typing import Optional, cast

# from rcrscore.entities import Building, Entity, EntityID, FireBrigade, Human, Refuge

# from adf_core_python.core.agent.communication.message_manager import MessageManager
# from adf_core_python.core.agent.develop.develop_data import DevelopData
# from adf_core_python.core.agent.info.agent_info import AgentInfo
# from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
# from adf_core_python.core.agent.info.world_info import WorldInfo
# from adf_core_python.core.agent.module.module_manager import ModuleManager
# from adf_core_python.core.component.module.algorithm.clustering import Clustering
# from adf_core_python.core.component.module.algorithm.path_planning import PathPlanning
# from adf_core_python.core.component.module.complex.search import Search
# from adf_core_python.core.logger.logger import get_agent_logger


# class SampleSearch(Search):
#   def __init__(
#     self,
#     agent_info: AgentInfo,
#     world_info: WorldInfo,
#     scenario_info: ScenarioInfo,
#     module_manager: ModuleManager,
#     develop_data: DevelopData,
#   ) -> None:
#     super().__init__(
#       agent_info, world_info, scenario_info, module_manager, develop_data
#     )

#     self._unreached_building_ids: set[EntityID] = set()
#     self._result: Optional[EntityID] = None

#     self._clustering: Clustering = cast(
#       Clustering,
#       module_manager.get_module(
#         "myteam.Search.Clustering",
#         "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
#       ),
#     )

#     self._path_planning: PathPlanning = cast(
#       PathPlanning,
#       module_manager.get_module(
#         "myteam.Search.PathPlanning",
#         "src.camp_default_2026.cached_path_planning.CachedPathPlanning",
#       ),
#     )

#     self._logger = get_agent_logger(
#       f"{self.__class__.__module__}.{self.__class__.__qualname__}",
#       self._agent_info,
#     )

#     self.register_sub_module(self._clustering)
#     self.register_sub_module(self._path_planning)

#   def update_info(self, message_manager: MessageManager) -> Search:
#     super().update_info(message_manager)

#     if not self._unreached_building_ids:
#         self._unreached_building_ids = self._get_search_targets()

#     searched_building_id = self._agent_info.get_position_entity_id()
#     if searched_building_id is not None:
#         self._unreached_building_ids.discard(searched_building_id)

#     return self

#   def calculate(self) -> Search:
#     position = self._agent_info.get_position_entity_id()

#     # まだターゲットに到着していない場合は、移動しきるためにターゲットを維持する
#     if self._result is not None and position != self._result:
#         if self._result in self._unreached_building_ids:
#             return self

#     if position is not None and position in self._unreached_building_ids:
#         self._unreached_building_ids.discard(position)

#     if not self._unreached_building_ids:
#         self._unreached_building_ids = self._get_search_targets()
#         if not self._unreached_building_ids:
#             self._result = None
#             return self

#     # 1. 自分に最も近い、埋没していない消防隊を見つける
#     fire_brigades = self._world_info.get_entities_of_types([FireBrigade])
#     nearest_fb: Optional[Entity] = None
#     min_fb_distance = float("inf")

#     if position is not None:
#         for fb in fire_brigades:
#             # 埋没していないことを確認する（埋設度がNoneまたは0より大きい場合はスキップ）
#             if isinstance(fb, Human):
#                 buriedness = fb.get_buriedness()
#                 if buriedness is None or buriedness > 0:
#                     continue

#             fb_pos = fb.get_position()
#             if fb_pos is not None:
#                 dist = self._path_planning.get_distance(position, fb_pos)
#                 if dist < min_fb_distance:
#                     min_fb_distance = dist
#                     nearest_fb = fb

#     # 2. その消防隊から最も近い、未探索の建物を選択する
#     target_building_id: Optional[EntityID] = None
#     min_building_distance = float("inf")

#     if nearest_fb is not None:
#         fb_pos = nearest_fb.get_position()
#         if fb_pos is not None:
#             for building_id in self._unreached_building_ids:
#                 dist = self._path_planning.get_distance(fb_pos, building_id)
#                 if dist < min_building_distance:
#                     min_building_distance = dist
#                     target_building_id = building_id

#     # 万が一、有効な消防隊が見つからない、または計算できない場合のフォールバック（自分からの最寄り）
#     if target_building_id is None and position is not None:
#         for building_id in self._unreached_building_ids:
#             dist = self._path_planning.get_distance(position, building_id)
#             if dist < min_building_distance:
#                 min_building_distance = dist
#                 target_building_id = building_id

#     self._result = target_building_id
#     return self

#   def get_target_entity_id(self) -> Optional[EntityID]:
#     return self._result

#   def _get_search_targets(self) -> set[EntityID]:
#     cluster_index: int = self._clustering.get_cluster_index(
#       self._agent_info.get_entity_id()
#     )
#     cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
#       cluster_index
#     )
#     building_entity_ids: list[EntityID] = [
#       entity.get_entity_id()
#       for entity in cluster_entities
#       if isinstance(entity, Building) and not isinstance(entity, Refuge)
#     ]

#     return set(building_entity_ids)

# # fb sticky second
# from typing import Optional, cast

# from rcrscore.entities import Building, Entity, EntityID, FireBrigade, Human, Refuge

# from adf_core_python.core.agent.communication.message_manager import MessageManager
# from adf_core_python.core.agent.develop.develop_data import DevelopData
# from adf_core_python.core.agent.info.agent_info import AgentInfo
# from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
# from adf_core_python.core.agent.info.world_info import WorldInfo
# from adf_core_python.core.agent.module.module_manager import ModuleManager
# from adf_core_python.core.component.module.algorithm.clustering import Clustering
# from adf_core_python.core.component.module.algorithm.path_planning import PathPlanning
# from adf_core_python.core.component.module.complex.search import Search
# from adf_core_python.core.logger.logger import get_agent_logger


# class SampleSearch(Search):
#   def __init__(
#     self,
#     agent_info: AgentInfo,
#     world_info: WorldInfo,
#     scenario_info: ScenarioInfo,
#     module_manager: ModuleManager,
#     develop_data: DevelopData,
#   ) -> None:
#     super().__init__(
#       agent_info, world_info, scenario_info, module_manager, develop_data
#     )

#     self._unreached_building_ids: set[EntityID] = set()
#     self._result: Optional[EntityID] = None

#     self._clustering: Clustering = cast(
#       Clustering,
#       module_manager.get_module(
#         "myteam.Search.Clustering",
#         "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
#       ),
#     )

#     self._path_planning: PathPlanning = cast(
#       PathPlanning,
#       module_manager.get_module(
#         "myteam.Search.PathPlanning",
#         "src.camp_default_2026.cached_path_planning.CachedPathPlanning",
#       ),
#     )

#     self._logger = get_agent_logger(
#       f"{self.__class__.__module__}.{self.__class__.__qualname__}",
#       self._agent_info,
#     )

#     self.register_sub_module(self._clustering)
#     self.register_sub_module(self._path_planning)

#   def update_info(self, message_manager: MessageManager) -> Search:
#     super().update_info(message_manager)

#     if not self._unreached_building_ids:
#         self._unreached_building_ids = self._get_search_targets()

#     searched_building_id = self._agent_info.get_position_entity_id()
#     if searched_building_id is not None:
#         self._unreached_building_ids.discard(searched_building_id)

#     return self

#   def calculate(self) -> Search:
#     position = self._agent_info.get_position_entity_id()

#     # まだターゲットに到着していない場合は、移動しきるためにターゲットを維持する
#     if self._result is not None and position != self._result:
#         if self._result in self._unreached_building_ids:
#             return self

#     if position is not None and position in self._unreached_building_ids:
#         self._unreached_building_ids.discard(position)

#     if not self._unreached_building_ids:
#         self._unreached_building_ids = self._get_search_targets()
#         if not self._unreached_building_ids:
#             self._result = None
#             return self

#     # 1. 自分に最も近い、埋没していない消防隊を見つける
#     fire_brigades = self._world_info.get_entities_of_types([FireBrigade])
#     nearest_fb: Optional[Entity] = None
#     min_fb_distance = float("inf")

#     if position is not None:
#         for fb in fire_brigades:
#             # 埋没していないことを確認する（埋設度がNoneまたは0より大きい場合はスキップ）
#             if isinstance(fb, Human):
#                 buriedness = fb.get_buriedness()
#                 if buriedness is None or buriedness > 0:
#                     continue

#             fb_pos = fb.get_position()
#             if fb_pos is not None:
#                 dist = self._path_planning.get_distance(position, fb_pos)
#                 if dist < min_fb_distance:
#                     min_fb_distance = dist
#                     nearest_fb = fb

#     # 2. 候補となる建物のセットを作成（基本は未探索の建物）
#     candidate_buildings = set(self._unreached_building_ids)

#     # 注目している消防隊が建物内にいる場合、探索済みであっても候補（探索対象）に含める
#     if nearest_fb is not None:
#         fb_pos = nearest_fb.get_position()
#         if fb_pos is not None:
#             fb_entity = self._world_info.get_entity(fb_pos)
#             if isinstance(fb_entity, Building):
#                 candidate_buildings.add(fb_pos)

#     # 3. その消防隊から最も近い建物を選択する
#     target_building_id: Optional[EntityID] = None
#     min_building_distance = float("inf")

#     if nearest_fb is not None:
#         fb_pos = nearest_fb.get_position()
#         if fb_pos is not None:
#             for building_id in candidate_buildings:
#                 dist = self._path_planning.get_distance(fb_pos, building_id)
#                 if dist < min_building_distance:
#                     min_building_distance = dist
#                     target_building_id = building_id

#     # 万が一、有効な消防隊が見つからない、または計算できない場合のフォールバック（自分からの最寄り）
#     if target_building_id is None and position is not None:
#         for building_id in candidate_buildings:
#             dist = self._path_planning.get_distance(position, building_id)
#             if dist < min_building_distance:
#                 min_building_distance = dist
#                 target_building_id = building_id

#     self._result = target_building_id
#     return self

#   def get_target_entity_id(self) -> Optional[EntityID]:
#     return self._result

#   def _get_search_targets(self) -> set[EntityID]:
#     cluster_index: int = self._clustering.get_cluster_index(
#       self._agent_info.get_entity_id()
#     )
#     cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
#       cluster_index
#     )
#     building_entity_ids: list[EntityID] = [
#       entity.get_entity_id()
#       for entity in cluster_entities
#       if isinstance(entity, Building) and not isinstance(entity, Refuge)
#     ]

#     return set(building_entity_ids)
