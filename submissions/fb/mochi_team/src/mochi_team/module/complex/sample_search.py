
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

    # 未到達の建物IDを管理する集合
    self._unreached_building_ids: set[EntityID] = set()

    # 探索済みの建物ID
    self._searched_building_ids: set[EntityID] = set()

    # 次の探索対象となる建物ID
    self._result: Optional[EntityID] = None

    # クラスタリングモジュールを取得
    # エージェントが担当する探索範囲の決定に使用する
    self._clustering: Clustering = cast(
      Clustering,
      module_manager.get_module(
        "mochi_team.Search.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )

    # 経路計画モジュールを取得
    # 現在位置から探索対象までの経路距離の取得に使用する
    self._path_planning: PathPlanning = cast(
      PathPlanning,
      module_manager.get_module(
        "mochi_team.Search.PathPlanning",
        "src.camp_default_2026.cached_path_planning.CachedPathPlanning",
      ),
    )

    # ロガーを取得
    self._logger = get_agent_logger(
      f"{self.__class__.__module__}.{self.__class__.__qualname__}",
      self._agent_info,
    )

    # 使用するサブモジュールを登録
    self.register_sub_module(self._clustering)
    self.register_sub_module(self._path_planning)

  def update_info(self, message_manager: MessageManager) -> Search:
    super().update_info(message_manager)

    if self.get_count_update_info() > 1:
      return self

    # 現在位置のEntityIDを取得
    searched_building_id = self._agent_info.get_position_entity_id()

    # 未到達の建物に到着した場合、探索済みとして記録
    if searched_building_id in self._unreached_building_ids:
      self._unreached_building_ids.discard(searched_building_id)
      self._searched_building_ids.add(searched_building_id)

    # 探索候補がなくなった場合、未探索の建物だけを取得
    if len(self._unreached_building_ids) == 0:
      self._unreached_building_ids = (
        self._get_search_targets() - self._searched_building_ids
      )

    return self

  def calculate(self) -> Search:
    """未到達の建物から経路距離が最も短い建物を選択する。"""

    # エージェントの現在位置を取得
    position = self._agent_info.get_position_entity_id()

    # 現在位置を取得できない場合は探索対象を設定しない
    if position is None:
      self._result = None
      return self

    # 最も近い建物のIDと距離を初期化
    nearest_building_id: Optional[EntityID] = None
    nearest_distance = float("inf")

    # 未到達の建物を順番に評価
    for building_id in self._unreached_building_ids:

      # 現在位置から建物までの経路距離を取得
      distance = self._path_planning.get_distance(position, building_id)

      # これまでの最短距離より短ければ探索対象を更新
      if distance < nearest_distance:
        nearest_building_id = building_id
        nearest_distance = distance

    # 次の探索対象となる建物IDを保存
    self._result = nearest_building_id
    return self

  def get_target_entity_id(self) -> Optional[EntityID]:
    """決定した探索対象の建物IDを返す。"""
    return self._result

  def _get_search_targets(self) -> set[EntityID]:
    """担当クラスタ内にある避難所以外の建物IDを取得する。"""

    # 自分のエージェントが所属するクラスタ番号を取得
    cluster_index: int = self._clustering.get_cluster_index(
      self._agent_info.get_entity_id()
    )

    # 担当クラスタに含まれるエンティティを取得
    cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
      cluster_index
    )

    # 建物のみを抽出し、避難所（Refuge）は除外
    building_entity_ids: list[EntityID] = [
      entity.get_entity_id()
      for entity in cluster_entities
      if isinstance(entity, Building) and not isinstance(entity, Refuge)
    ]

    # 建物IDを集合に変換して返す
    return set(building_entity_ids)
