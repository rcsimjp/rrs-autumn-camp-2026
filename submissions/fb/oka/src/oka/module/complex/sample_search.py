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
    self._unreachable_building_ids: set[EntityID] = set()  # 到達不能な建物のブラックリスト
    self._result: Optional[EntityID] = None

    # スタック判定用の変数
    self._last_position_id: Optional[EntityID] = None
    self._stuck_count: int = 0

    # クラスタ巡回用のオフセット（自分のクラスタが終わったら隣へ行くため）
    self._cluster_offset: int = 0

    self._clustering: Clustering = cast(
      Clustering,
      module_manager.get_module(
        "oka.Search.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )

    self._path_planning: PathPlanning = cast(
      PathPlanning,
      module_manager.get_module(
        "oka.Search.PathPlanning",
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

    current_pos_id = self._agent_info.get_position_entity_id()
    if current_pos_id is not None:
      self._unreached_building_ids.discard(current_pos_id)

    # 改善1: 目的地にまだ着いていないのに、現在地が3ステップ変わっていなければスタックと判定
    if (
      self._result is not None
      and current_pos_id != self._result
      and current_pos_id == self._last_position_id
    ):
      self._stuck_count += 1
      if self._stuck_count >= 3:
        self._unreached_building_ids.discard(self._result)
        self._unreachable_building_ids.add(self._result)  # ブラックリストに登録
        self._stuck_count = 0
    else:
      self._last_position_id = current_pos_id
      self._stuck_count = 0

    # 改善3: 未探索リストが空になったら、次のクラスタからターゲットを補充する
    if len(self._unreached_building_ids) == 0:
      targets = self._get_search_targets()
      self._unreached_building_ids = targets - self._unreachable_building_ids

      # もし現在のクラスタに有効な建物がなければ、隣のクラスタへ移行する
      if len(self._unreached_building_ids) == 0:
        self._cluster_offset += 1
        targets = self._get_search_targets()
        self._unreached_building_ids = targets - self._unreachable_building_ids

        # それでも空ならブラックリストをリセットして再取得
        if len(self._unreached_building_ids) == 0:
          self._unreachable_building_ids.clear()
          self._unreached_building_ids = targets

    return self

  def calculate(self) -> Search:
    position = self._agent_info.get_position_entity_id()
    if position is None:
      self._result = None
      return self

    nearest_building_id: Optional[EntityID] = None
    best_score = float("inf")

    for building_id in list(self._unreached_building_ids):
      entity = self._world_info.get_entity(building_id)
      score_weight = 1.0

      # 改善2 & 4: 建物の倒壊度（brokenness）を確認する
      if isinstance(entity, Building):
        brokenness = entity.get_brokenness()
        if brokenness is not None:
          if brokenness == 0:
            # 壊れていない（無傷の）建物は市民が埋まっていないので除外してスキップ
            self._unreached_building_ids.discard(building_id)
            continue
          else:
            # 壊れている建物は優先度を上げる（評価距離を0.7倍にして選ばれやすくする）
            score_weight = 0.7

      distance = self._path_planning.get_distance(position, building_id)
      score = distance * score_weight

      if score < best_score:
        nearest_building_id = building_id
        best_score = score

    self._result = nearest_building_id
    return self

  def get_target_entity_id(self) -> Optional[EntityID]:
    return self._result

  def _get_search_targets(self) -> set[EntityID]:
    base_index: int = self._clustering.get_cluster_index(
      self._agent_info.get_entity_id()
    )
    cluster_num: int = self._clustering.get_cluster_number()

    # 自分のクラスタが終わったら、順番に隣のクラスタの番号を計算する
    if cluster_num > 0:
      target_index = (base_index + self._cluster_offset) % cluster_num
    else:
      target_index = base_index

    cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
      target_index
    )

    building_entity_ids: list[EntityID] = []
    for entity in cluster_entities:
      if isinstance(entity, Building) and not isinstance(entity, Refuge):
        # すでに「壊れていない（0）」と分かっている建物は最初からリストに入れない
        brokenness = entity.get_brokenness()
        if brokenness is not None and brokenness == 0:
          continue
        building_entity_ids.append(entity.get_entity_id())

    return set(building_entity_ids)