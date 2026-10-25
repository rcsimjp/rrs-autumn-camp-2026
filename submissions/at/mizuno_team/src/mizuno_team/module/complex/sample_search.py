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

    # 探索クラスタを管理するフラグ変数（この変数のカウントを1ずつ増やすことで，各クラスタを順番に探索する）
    self._cluster_switch_count: int = 0
    self._has_initialized_search_targets: bool = False

    self._clustering: Clustering = cast(
      Clustering,
      module_manager.get_module(
        "mizuno_team.Search.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )

    self._path_planning: PathPlanning = cast(
      PathPlanning,
      module_manager.get_module(
        "mizuno_team.Search.PathPlanning",
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
    if self.get_count_update_info() > 1:
      return self

    self._logger.debug(
      f"unreached_building_ids: {[str(id) for id in self._unreached_building_ids]}"
    )

    searched_building_id = self._agent_info.get_position_entity_id()
    if searched_building_id is not None:
      self._unreached_building_ids.discard(searched_building_id)

    if len(self._unreached_building_ids) == 0:
      # 初回の探索対象設定ではクラスタ番号を進めない
      if self._has_initialized_search_targets:
        self._cluster_switch_count += 1

      self._unreached_building_ids = self._get_search_targets()
      self._has_initialized_search_targets = True

    return self

  def calculate(self) -> Search:
    position = self._agent_info.get_position_entity_id()
    if position is None:
      self._result = None
      return self

    nearest_building_id: Optional[EntityID] = None
    nearest_distance = float("inf")
    for building_id in self._unreached_building_ids:
      distance = self._path_planning.get_distance(position, building_id)
      if distance < nearest_distance:
        nearest_building_id = building_id
        nearest_distance = distance
    self._result = nearest_building_id
    return self

  def get_target_entity_id(self) -> Optional[EntityID]:
    return self._result

  def _get_search_targets(self) -> set[EntityID]:
    # エージェントが所属しているクラスタ番号を取得
    current_cluster_index: int = self._clustering.get_cluster_index(
        self._agent_info.get_entity_id()
    )

    # クラスタの総数を取得
    cluster_count: int = self._clustering.get_cluster_number()

    # クラスタが存在しない場合は探索対象なし
    if cluster_count <= 0:
        return set()

    # 探索対象とするクラスタ番号を計算
    target_cluster_index: int = (
        current_cluster_index + self._cluster_switch_count
    ) % cluster_count

    # 対象クラスタに所属するエンティティを取得
    cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
        target_cluster_index
    )

    # 対象クラスタ内の建物を抽出（避難所を除く）
    building_entity_ids: list[EntityID] = [
        entity.get_entity_id()
        for entity in cluster_entities
        if isinstance(entity, Building) and not isinstance(entity, Refuge)
    ]

    return set(building_entity_ids)
