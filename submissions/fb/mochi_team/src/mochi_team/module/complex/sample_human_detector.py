
from math import ceil
from typing import Optional, cast

from adf_core_python.core.agent.develop.develop_data import DevelopData
from adf_core_python.core.agent.info.agent_info import AgentInfo
from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
from adf_core_python.core.agent.info.world_info import WorldInfo
from adf_core_python.core.agent.module.module_manager import ModuleManager
from adf_core_python.core.component.module.algorithm.clustering import Clustering
from adf_core_python.core.component.module.complex.human_detector import HumanDetector
from adf_core_python.core.logger.logger import get_agent_logger
from rcrscore.entities import AmbulanceTeam, Civilian, Entity, EntityID, FireBrigade, Human, Refuge
from rcrscore.urn import EntityURN


class SampleHumanDetector(HumanDetector):
  # 時間の単位はターン。速度と掘削速度は初期の推定値であり、実測で調整する。
  _MOVE_DISTANCE_PER_TURN = 30000.0  # mm/turn、直線距離による概算
  _RESCUE_PER_TURN = 1.0  # 一隊で掘る場合の埋没度減少量
  _TRANSPORT_FALLBACK = 10.0  # 避難所への距離が不明な場合
  _TRANSPORT_OVERHEAD = 2.0  # 積載・降車。救急隊の到着待ちは未考慮
  _CLUSTER_FACTOR = 0.95
  _CURRENT_TARGET_FACTOR = 0.85
  _MAX_RESCUE_TEAM = 3
  _URGENT_SLACK = 20.0  # 搬送完了までの余裕が20ターン以内なら緊急

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

    # クラスタリングモジュールを取得
    # 消防隊が担当する範囲内の市民を優先するために使用
    self._clustering: Clustering = cast(
      Clustering,
      module_manager.get_module(
        "mochi_team.HumanDetector.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )

    # クラスタリングモジュールを登録
    self.register_sub_module(self._clustering)

    # 現在の救出対象となる市民のID
    self._result: Optional[EntityID] = None

    # ロガーを取得
    self._logger = get_agent_logger(
      f"{self.__class__.__module__}.{self.__class__.__qualname__}",
      self._agent_info,
    )

  def calculate(self) -> HumanDetector:
    """全候補を毎ターン再評価する。無効になった現在の対象も選び直す。"""
    self._result = self._select_target()
    return self

  def _select_target(self) -> Optional[EntityID]:
    """救出時間・緊急度・救命の見込みから対象を選ぶ。"""
    brigades = [
      cast(FireBrigade, entity)
      for entity in self._world_info.get_entities_of_types([FireBrigade])
      if isinstance(entity, FireBrigade)
      and entity.get_position() is not None
      and (entity.get_hp() is None or entity.get_hp() > 0)
      and (entity.get_buriedness() is None or entity.get_buriedness() == 0)
    ]
    my_id = self._agent_info.get_entity_id()
    if len(brigades) > 1 and any(b.get_entity_id() == my_id for b in brigades):
      return self._allocate_team_target(brigades)

    cluster_index = self._clustering.get_cluster_index(
      self._agent_info.get_entity_id()
    )
    cluster_ids = set()
    if cluster_index >= 0:
      cluster_ids = {
        entity.get_entity_id()
        for entity in self._clustering.get_cluster_entities(cluster_index)
      }
    refuges = self._world_info.get_entities_of_types([Refuge])
    best_target: Optional[EntityID] = None
    best_score = (float("inf"), float("inf"))

    for entity in self._world_info.get_entities_of_types([Civilian, AmbulanceTeam]):
      target_id = entity.get_entity_id()
      if not self._is_valid_human(target_id):
        continue
      target = cast(Human, entity)
      distance = self._world_info.get_distance(
        self._agent_info.get_entity_id(), target_id
      )
      # 不明な距離を「近い」として評価しない。
      if distance is None or distance < 0:
        continue
      move_time = ceil(distance / self._MOVE_DISTANCE_PER_TURN)
      dig_time = ceil(cast(int, target.get_buriedness()) / self._RESCUE_PER_TURN)
      transport_times = []
      for refuge in refuges:
        refuge_distance = self._world_info.get_distance(
          target_id, refuge.get_entity_id()
        )
        if refuge_distance is not None and refuge_distance >= 0:
          transport_times.append(ceil(refuge_distance / self._MOVE_DISTANCE_PER_TURN))
      transport_time = (
        min(transport_times) if transport_times else self._TRANSPORT_FALLBACK
      ) + self._TRANSPORT_OVERHEAD
      if isinstance(target, AmbulanceTeam):
        transport_time = 0.0  # 復帰は掘り起こし完了時。搬送待ちは含めない。
      priority, score = self._target_priority(target, move_time + dig_time, transport_time)
      # 区域外も候補とし、同程度の対象なら区域内・現在の対象を優遇する。
      if target.get_position() in cluster_ids or target_id in cluster_ids:
        score *= self._CLUSTER_FACTOR
      if target_id == self._result:
        score *= self._CURRENT_TARGET_FACTOR
      if (priority, score) < best_score:
        best_score = (priority, score)
        best_target = target_id

    return best_target

  def _allocate_team_target(self, brigades: list[FireBrigade]) -> Optional[EntityID]:
    """観測できる全隊について、同じ計算順で最大3隊ずつ割り当てる。

    他隊の目標を受信しているわけではなく、位置から割り当てを推定する。
    情報が一致している場合に人数上限が成立する。個別のクラスタ・継続加点は
    共通の割り当てを崩すため、この方式では使用しない。
    """
    targets = sorted(
      (
        cast(Human, entity)
        for entity in self._world_info.get_entities_of_types([Civilian, AmbulanceTeam])
        if self._is_valid_human(entity.get_entity_id())
      ),
      key=lambda entity: entity.get_entity_id().get_value(),
    )
    available = {b.get_entity_id(): b for b in brigades}
    refuges = self._world_info.get_entities_of_types([Refuge])
    transport_times: dict[EntityID, float] = {}
    travel_times: dict[tuple[EntityID, EntityID], int] = {}
    for target in targets:
      target_id = target.get_entity_id()
      refuge_times = []
      for refuge in refuges:
        distance = self._world_info.get_distance(target_id, refuge.get_entity_id())
        if distance is not None and distance >= 0:
          refuge_times.append(ceil(distance / self._MOVE_DISTANCE_PER_TURN))
      transport_times[target_id] = (
        0.0 if isinstance(target, AmbulanceTeam) else
        (min(refuge_times) if refuge_times else self._TRANSPORT_FALLBACK)
        + self._TRANSPORT_OVERHEAD
      )
      for brigade in brigades:
        brigade_id = brigade.get_entity_id()
        distance = self._world_info.get_distance(brigade_id, target_id)
        if distance is not None and distance >= 0:
          travel_times[brigade_id, target_id] = (
            0 if brigade.get_position() == target.get_position()
            else max(1, ceil(distance / self._MOVE_DISTANCE_PER_TURN))
          )

    while available and targets:
      best_score = (float("inf"), float("inf"))
      best_target = None
      best_team: list[EntityID] = []
      for target in targets:
        target_id = target.get_entity_id()
        nearby = sorted(
          (bid for bid in available if (bid, target_id) in travel_times),
          key=lambda bid: (travel_times[bid, target_id], bid.get_value()),
        )
        if not nearby:
          continue
        # 救出完了後に到着する隊を人数に含めない。
        team = [nearby[0]]
        finish = travel_times[team[0], target_id] + ceil(
          cast(int, target.get_buriedness()) / self._RESCUE_PER_TURN
        )
        for bid in nearby[1:self._MAX_RESCUE_TEAM]:
          if travel_times[bid, target_id] >= finish:
            break
          team.append(bid)
          finish = self._team_rescue_time(
            cast(int, target.get_buriedness()),
            [travel_times[member, target_id] for member in team],
          )
        score = self._target_priority(target, finish, transport_times[target_id])
        if score < best_score:
          best_score, best_target, best_team = score, target, team
      if best_target is None:
        break
      if self._agent_info.get_entity_id() in best_team:
        return best_target.get_entity_id()
      for bid in best_team:
        del available[bid]
      targets.remove(best_target)
    return None

  def _team_rescue_time(self, buriedness: int, arrivals: list[int]) -> int:
    """先着隊は到着時から掘り、後着隊は合流後から掘る場合の完了時刻。"""
    ordered = sorted(arrivals)
    remaining = float(buriedness)
    time = ordered[0]
    workers = 1
    for arrival in ordered[1:]:
      work = (arrival - time) * workers * self._RESCUE_PER_TURN
      if remaining <= work:
        return time + ceil(remaining / (workers * self._RESCUE_PER_TURN))
      remaining -= work
      time = arrival
      workers += 1
    return time + ceil(remaining / (workers * self._RESCUE_PER_TURN))

  def _target_priority(
    self, target: Human, rescue_time: float, transport_time: float,
  ) -> tuple[int, float]:
    """緊急で救命可能な市民→救急隊→余裕のある市民→予測上厳しい市民。

    余命と所要時間は概算。予測上厳しい対象も除外せず、最後の候補に残す。
    """
    hp = cast(int, target.get_hp())
    damage = target.get_damage()
    cost = self._rescue_cost(hp, damage, rescue_time, transport_time)
    if isinstance(target, AmbulanceTeam):
      return (1, cost)
    if damage is not None and damage > 0:
      slack = hp / damage - rescue_time - transport_time
      if 0 <= slack <= self._URGENT_SLACK:
        return (0, cost)
      if slack < 0:
        return (3, cost)
    return (2, cost)

  @staticmethod
  def _rescue_cost(
    hp: int, damage: Optional[int], rescue_time: float, transport_time: float,
  ) -> float:
    """小さいほど優先。予測が厳しい市民も有限のコストで候補に残す。"""
    cost = max(1.0, rescue_time)
    if damage is None or damage <= 0:
      # 不明・ゼロdamageから余命を決めつけず、所要時間で評価する。
      return cost
    life_time = hp / damage
    total_time = rescue_time + transport_time
    slack = life_time - total_time
    if slack >= 0:
      # 救命の余裕が少ないときは最大2倍の優遇。
      urgency = total_time / max(life_time, 1.0)
      return cost / (1.0 + urgency)
    # 間に合わない予測でも除外しない。余裕0の前後で連続にする。
    risk = min(4.0, -slack / max(life_time, 1.0))
    return cost * (0.5 + risk)

  def _is_valid_human(self, target_entity_id: EntityID) -> bool:
    """指定された市民・救急隊が消防隊の救出対象として有効か判定する。"""

    # 指定されたIDからエンティティを取得
    target: Optional[Entity] = self._world_info.get_entity(target_entity_id)

    # 市民と救急隊のみを救出する
    if not isinstance(target, (Civilian, AmbulanceTeam)):
      return False

    # 市民のHPを取得
    hp: Optional[int] = target.get_hp()

    # HPが不明、または0以下の場合は救出対象外
    if hp is None or hp <= 0:
      return False

    # 市民の埋没度を取得
    buriedness: Optional[int] = target.get_buriedness()

    # 埋没度が不明、または0以下の場合は救出対象外
    # 埋没している市民・救急隊のみを掘り起こす
    if buriedness is None or buriedness <= 0:
      return False

    # 市民の現在位置のEntityIDを取得
    position_entity_id: Optional[EntityID] = target.get_position()

    # 市民の位置情報が不明な場合は救出対象外
    if position_entity_id is None:
      return False

    # 市民が存在する位置のエンティティを取得
    position: Optional[Entity] = self._world_info.get_entity(
      position_entity_id
    )

    # 位置のエンティティを取得できない場合は救出対象外
    if position is None:
      return False

    # 市民が存在する場所の種類を取得
    urn: EntityURN = position.get_urn()

    # 避難所にいる市民は救出対象外
    if urn == EntityURN.REFUGE:
      return False

    # 救急隊に搬送されている市民は救出対象外
    if urn == EntityURN.AMBULANCE_TEAM:
      return False

    # すべての条件を満たした場合は救出対象
    return True

  def get_target_entity_id(self) -> Optional[EntityID]:
    """現在選択されている救出対象の市民IDを返す。"""
    return self._result
