from typing import Optional, cast

from rcrscore.entities import AmbulanceTeam, Building, Entity, EntityID, Human, Refuge

from adf_core_python.core.agent.communication.message_manager import MessageManager
from adf_core_python.core.agent.communication.standard.bundle.information.message_ambulance_team import (
    MessageAmbulanceTeam,
)
from adf_core_python.core.agent.communication.standard.bundle.standard_message_priority import (
    StandardMessagePriority,
)
from adf_core_python.core.agent.communication.standard.bundle.information.message_civilian import (
    MessageCivilian,
)
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
    self._message_manager: Optional[MessageManager] = None
    # 他のATが探索目標としている建物 (at_id -> (building_id, step))
    self._other_search_claims: dict[EntityID, tuple[EntityID, int]] = {}
    # スタック（到達不能・渋滞）建物のブラックリスト (building_id -> expiry_step)
    self._blacklisted_buildings: dict[EntityID, int] = {}
    self._current_search_target: Optional[EntityID] = None
    self._target_steps: int = 0
    self._last_broadcasted_search: Optional[EntityID] = None

    self._clustering: Clustering = cast(
      Clustering,
      module_manager.get_module(
        "camp_at.Search.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )

    self._path_planning: PathPlanning = cast(
      PathPlanning,
      module_manager.get_module(
        "camp_at.Search.PathPlanning",
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

    self._message_manager = message_manager
    current_time = self._agent_info.get_time()
    my_id = self._agent_info.get_entity_id()

    # 期限切れのブラックリストを解除
    expired_bl = [b for b, exp in self._blacklisted_buildings.items() if current_time >= exp]
    for b in expired_bl:
      del self._blacklisted_buildings[b]

    # 他のATの探索目標クレーム期限切れ（15ステップ超）をパージ
    expired_claims = [a for a, (_, t) in self._other_search_claims.items() if current_time - t > 15]
    for a in expired_claims:
      del self._other_search_claims[a]

    # 初回またはクラスタ完了時はターゲットを補充
    if len(self._unreached_building_ids) == 0:
      self._unreached_building_ids = self._get_search_targets()
      if len(self._unreached_building_ids) == 0:
        self._unreached_building_ids = self._get_fallback_search_targets()

    # 1. 自分が直接滞在した建物を探索済みとする
    searched_building_id = self._agent_info.get_position_entity_id()
    if searched_building_id is not None:
      self._unreached_building_ids.discard(searched_building_id)

    # 2. 見通し視覚 (Line-of-Sight) で観測された建物を探索済みとする
    change_set = self._world_info.get_change_set()
    if change_set is not None:
      for changed_id in change_set.get_changed_entities():
        entity = self._world_info.get_entity(changed_id)
        if isinstance(entity, Building):
          self._unreached_building_ids.discard(changed_id)

    # 3. 他の救急隊(AT)からの無線通信による探索済み建物の反映＆探索目標の共有
    for msg in message_manager.get_received_message_list():
      if isinstance(msg, MessageCivilian):
        pos = msg.get_civilian_position()
        if pos is not None:
          self._unreached_building_ids.discard(pos)
      elif isinstance(msg, MessageAmbulanceTeam):
        pos = msg.get_ambulance_team_position()
        if pos is not None:
          self._unreached_building_ids.discard(pos)

        sender_id = msg.get_ambulance_team_entity_id() or msg.get_sender_entity_id()
        target_id = msg.get_target_entity_id()
        action = msg.get_action()
        if sender_id is not None and sender_id != my_id and target_id is not None:
          # 他のATが探索(ACTION_MOVE)している建物を記録して重複を回避
          if action == MessageAmbulanceTeam.ACTION_MOVE and target_id.get_value() != -1:
            self._other_search_claims[sender_id] = (target_id, current_time)

    # 4. クラスタ内の全建物が完了したら全マップの未探索建物を対象にする
    if len(self._unreached_building_ids) == 0:
      self._unreached_building_ids = self._get_fallback_search_targets()

    self._logger.debug(
      f"unreached_building_ids count: {len(self._unreached_building_ids)}"
    )

    return self

  def _get_fallback_search_targets(self) -> set[EntityID]:
    all_buildings = self._world_info.get_entities_of_types([Building])
    return {
      b.get_entity_id()
      for b in all_buildings
      if not isinstance(b, Refuge)
    }

  def calculate(self) -> Search:
    # 自身が埋没中の場合は移動不可能（無駄なActionMoveを抑止しActionRestへフォールバック）
    myself = self._agent_info.get_myself()
    if isinstance(myself, Human) and (myself.get_buriedness() or 0) > 0:
      self._result = None
      return self

    position = self._agent_info.get_position_entity_id()
    if position is None:
      self._result = None
      return self

    current_time = self._agent_info.get_time()
    my_id = self._agent_info.get_entity_id()
    my_id_val = my_id.get_value()

    # ★【スタック・交通渋滞検知】同じ建物に10ステップ以上向かっても到着できない場合は一時迂回
    if self._result is not None:
      if self._result == self._current_search_target:
        self._target_steps += 1
        if self._target_steps >= 10:
          self._blacklisted_buildings[self._result] = current_time + 25
          self._unreached_building_ids.discard(self._result)
          self._result = None
          self._target_steps = 0
      else:
        self._current_search_target = self._result
        self._target_steps = 1

    # 他のATの物理位置（同一建物への探索密集を完全回避）
    other_at_positions = {
      at.get_position()
      for at in self._world_info.get_entities_of_types([AmbulanceTeam])
      if at.get_entity_id() != my_id and at.get_position() is not None
    }

    # ★【目標コミットメント・ヒステリシス】（発振・反復横跳びの完全根絶）
    # 既存の探索ターゲットがあり、未探索かつ未ブラックリストの場合
    if (
      self._result is not None
      and self._result in self._unreached_building_ids
      and self._result not in self._blacklisted_buildings
    ):
      # 他のATが既に物理的にその建物内に到着している場合は譲る
      if self._result in other_at_positions:
        self._result = None
      else:
        # 他のATも同じ建物を探索予約している場合、非対称調停（近い方が維持、遠い方が譲る）
        yield_to_peer = False
        my_dist = self._path_planning.get_distance(position, self._result)
        if my_dist == float("inf"):
          my_dist = self._world_info.get_distance(position, self._result)

        for other_id, (claimed_b, _) in self._other_search_claims.items():
          if other_id != my_id and claimed_b == self._result:
            other_ent = self._world_info.get_entity(other_id)
            if isinstance(other_ent, AmbulanceTeam) and other_ent.get_position() is not None:
              o_pos = other_ent.get_position()
              o_dist = self._path_planning.get_distance(o_pos, self._result)
              if o_dist == float("inf"):
                o_dist = self._world_info.get_distance(o_pos, self._result)
              # 相手が自分より明確に近い、または同距離でIDが小さい場合に自分が譲る
              if o_dist < my_dist or (o_dist == my_dist and other_id.get_value() < my_id_val):
                yield_to_peer = True
                break

        if not yield_to_peer:
          # 自分が最優先！現在の探索目標を維持して直進（毎ターンの目移り・反復横跳びを完全防止）
          return self
        else:
          self._result = None

    cluster_index: int = self._clustering.get_cluster_index(
      self._agent_info.get_entity_id()
    )
    cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
      cluster_index
    )
    my_cluster_ids = {e.get_entity_id() for e in cluster_entities}

    # 他のATが探索目標としている建物
    other_claimed_buildings = {
      bid for bid, _ in self._other_search_claims.values()
    }

    best_building_id: Optional[EntityID] = None
    best_cost = float("inf")

    for building_id in self._unreached_building_ids:
      if building_id in self._blacklisted_buildings:
        continue

      distance = self._path_planning.get_distance(position, building_id)
      if distance == float("inf"):
        distance = self._world_info.get_distance(position, building_id)

      # クラスタ内を最優先、クラスタ外は距離コスト加算
      cluster_penalty = 0.0 if building_id in my_cluster_ids else 50000.0

      # 他のATが物理的に滞在、または無線で探索予約している建物は大幅ペナルティで完全分散
      crowding_penalty = 0.0
      if building_id in other_at_positions:
        crowding_penalty += 70000.0
      if building_id in other_claimed_buildings:
        crowding_penalty += 80000.0

      # エージェントごとの固有分散バイアス（複数エージェントが同一目標に収束するのを防止）
      agent_bias = ((building_id.get_value() * 37 + my_id_val * 67) % 31) * 800.0

      total_cost = distance + cluster_penalty + crowding_penalty + agent_bias
      if total_cost < best_cost:
        best_cost = total_cost
        best_building_id = building_id

    self._result = best_building_id
    if self._result != self._last_broadcasted_search:
      self._broadcast_search_target(self._result)

    return self

  def _broadcast_search_target(self, building_id: Optional[EntityID]) -> None:
    """探索目標建物を同部隊(AT)に共有し、探索のボトルネック・密集を完全回避"""
    if self._message_manager is None:
      return
    if building_id is None and self._last_broadcasted_search is None:
      return

    myself = self._agent_info.get_myself()
    if isinstance(myself, AmbulanceTeam):
      my_id = self._agent_info.get_entity_id()
      msg = MessageAmbulanceTeam(
        True,
        myself,
        MessageAmbulanceTeam.ACTION_MOVE,
        building_id,
        StandardMessagePriority.LOW,
        my_id,
      )
      self._message_manager.add_message(msg)
      self._last_broadcasted_search = building_id

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
