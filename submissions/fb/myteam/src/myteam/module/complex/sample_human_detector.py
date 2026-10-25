from math import ceil, isfinite
from typing import Optional, cast

from rcrscore.entities import AmbulanceTeam, Civilian, Entity, EntityID, FireBrigade, Human
from rcrscore.urn import EntityURN, PropertyURN

from adf_core_python.core.agent.action.ambulance.action_rescue import ActionRescue
from adf_core_python.core.agent.communication.message_manager import MessageManager
from adf_core_python.core.agent.develop.develop_data import DevelopData
from adf_core_python.core.agent.info.agent_info import AgentInfo
from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
from adf_core_python.core.agent.info.world_info import WorldInfo
from adf_core_python.core.agent.module.module_manager import ModuleManager
from adf_core_python.core.component.module.algorithm.clustering import Clustering
from adf_core_python.core.component.module.algorithm.path_planning import PathPlanning
from adf_core_python.core.component.module.complex.human_detector import HumanDetector
from adf_core_python.core.logger.logger import get_agent_logger

from src.myteam.communication.rescue_report import create_rescue_completed_messages


class SampleHumanDetector(HumanDetector):
  MIN_ACTIVE_STEPS_AFTER_RESCUE = 30
  # 170ステップ以降は市民に時間を使うため、消防隊・救急隊を救助候補から外す。
  RESCUE_AGENT_TIME_LIMIT = 170

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
    # 担当区域を決めるクラスタリングを設定から読み込む。
    self._clustering: Clustering = cast(
      Clustering,
      module_manager.get_module(
        "myteam.HumanDetector.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )
    self.register_sub_module(self._clustering)

    # Searchと同じ設定の経路計算を利用し、道路・建物間の経路距離を求める。
    self._path_planning: PathPlanning = cast(
      PathPlanning,
      module_manager.get_module(
        "myteam.Search.PathPlanning",
        "src.camp_default_2026.cached_path_planning.CachedPathPlanning",
      ),
    )
    self.register_sub_module(self._path_planning)

    # 現在の救助対象のID。対象がいなければ None。
    self._result: Optional[EntityID] = None
    # 同じ救出完了を繰り返し報告しないための記録。
    self._reported_rescue_ids: set[EntityID] = set()
    self._logger = get_agent_logger(
      f"{self.__class__.__module__}.{self.__class__.__qualname__}",
      self._agent_info,
    )

  # 通信の処理は、対象を選ぶcalculateではなく毎ステップの情報更新で行う。
  def update_info(self, message_manager: MessageManager) -> HumanDetector:
    super().update_info(message_manager)
    if self.get_count_update_info() > 1:
      return self
    self._report_rescue_completion(message_manager)
    return self

  def _report_rescue_completion(self, message_manager: MessageManager) -> None:
    change_set = self._world_info.get_change_set()
    # 再び埋没したことを知覚した場合は、次の救出完了を報告できるようにする。
    for entity_id in change_set.get_changed_entities():
      buriedness = change_set.get_changed_property(entity_id, PropertyURN.BURIEDNESS)
      if buriedness is not None and (buriedness.get_value() or 0) > 0:
        self._reported_rescue_ids.discard(entity_id)

    # 「救助対象を選んだ」だけでは報告しない。前ステップの実際の行動を確認する。
    previous_action = self._agent_info.get_executed_action(self._agent_info.get_time() - 1)
    if not isinstance(previous_action, ActionRescue):
      return
    target_id = previous_action.target_id
    if target_id in self._reported_rescue_ids:
      return

    # 今回の知覚で埋没度0を確認した時だけ、掘り出し完了と判断する。
    # 埋没度が残っている場合、知覚できなかった場合、死亡した場合は送らない。
    buriedness = change_set.get_changed_property(target_id, PropertyURN.BURIEDNESS)
    if buriedness is None or buriedness.get_value() != 0:
      return
    target = self._world_info.get_entity(target_id)
    if not isinstance(target, (Civilian, AmbulanceTeam)):
      return
    hp = target.get_hp()
    if hp is None or hp <= 0 or target.get_buriedness() != 0 or target.get_position() is None:
      return
    myself = self._agent_info.get_myself()
    if not isinstance(myself, FireBrigade):
      return

    for message in create_rescue_completed_messages(myself, target):
      message_manager.add_message(message)
    self._reported_rescue_ids.add(target_id)

  def calculate(self) -> HumanDetector:
    # 救出後の推定活動時間などを比較するため、救助中でも毎ステップ選び直す。
    self._result = self._select_target()
    return self

  def _select_target(self) -> Optional[EntityID]:
    # 今回のChangeSetに含まれる市民・消防隊・救急隊を候補にする。
    change_set = self._world_info.get_change_set()
    candidate_ids = change_set.get_changed_entities()
    # 救助中の対象は、今回知覚できなくても候補に残す。
    if self._result is not None:
      candidate_ids.add(self._result)

    selected_human_id: Optional[EntityID] = None
    best_priority: Optional[tuple[int, int, int, float, int]] = None

    for entity_id in candidate_ids:
      entity = self._world_info.get_entity(entity_id)
      if not isinstance(entity, (Civilian, FireBrigade, AmbulanceTeam)):
        continue
      if not self._is_valid_human(entity_id):
        continue

      priority = self._get_priority(entity)
      if priority is None:
        continue
      if best_priority is None or priority < best_priority:
        best_priority = priority
        selected_human_id = entity_id

    # 有効な候補がいなければ None を返す。
    return selected_human_id

  def _get_priority(self, entity: Human) -> Optional[tuple[int, int, int, float, int]]:
    # 人のIDではなく、所在する道路・建物のIDで経路距離を計算する。
    entity_id = entity.get_entity_id()
    position_id = self._agent_info.get_position_entity_id()
    target_position_id = entity.get_position()
    if position_id is None or target_position_id is None:
      return None
    if target_position_id == position_id:
      move_steps = 0
    else:
      distance = self._path_planning.get_distance(position_id, target_position_id)
      # 経路がない対象は候補から外し、無限大の切り上げも避ける。
      if not isfinite(distance):
        return None
      # 経路距離 / 40,000 の切り上げで移動ステップ数を概算する。
      move_steps = max(1, ceil(distance / 40_000))

    # 救助条件で確認済みなので、HP・埋没度・damage は数値として扱える。
    hp = cast(int, entity.get_hp())
    buriedness = cast(int, entity.get_buriedness())
    damage = cast(int, entity.get_damage())
    estimated_damage = damage
    if buriedness > 0 and damage == 0:
      damage_precision = self._scenario_info.get_value(
        "perception.los.precision.damage", 0
      )
      # 精度80の四捨五入なら実際のdamageは0〜39。上限39を仮値に使う。
      # 観測値は変更せず、緊急性の計算にだけ使う。
      estimated_damage = max(0, damage_precision // 2 - 1)
    # 精度不明・丸め誤差なしの場合などは、ゼロ除算を避ける。
    survival_steps = hp / estimated_damage if estimated_damage > 0 else float("inf")

    # 消防隊1台で掘り出す前提。救出後に30ステップ以上残る隊員を優先する。
    active_steps = survival_steps - move_steps - buriedness
    is_rescue_agent = isinstance(entity, (FireBrigade, AmbulanceTeam))
    agent_priority = 0 if (
      is_rescue_agent and active_steps >= self.MIN_ACTIVE_STEPS_AFTER_RESCUE
    ) else 1

    # 隊員優先の有無 → 移動ステップ → 埋没度 → HP/damage の順で比較する。
    # 救出後の推定活動時間が優先条件に満たない隊員は、市民と同じ基準で比較する。
    return (agent_priority, move_steps, buriedness, survival_steps, entity_id.get_value())

  def _is_valid_human(self, target_entity_id: EntityID) -> bool:
    # 自分自身は救助対象にしない。
    if target_entity_id == self._agent_info.get_entity_id():
      return False
    # 人であることを確認し、死亡者や必要な情報が不明な人を除外する。
    target: Optional[Entity] = self._world_info.get_entity(target_entity_id)
    if target is None:
      return False
    if not isinstance(target, Human):
      return False
    # 救助中でも、打ち切り時刻に達した隊員は対象から外す。市民には適用しない。
    if (
      isinstance(target, (FireBrigade, AmbulanceTeam))
      and self._agent_info.get_time() >= self.RESCUE_AGENT_TIME_LIMIT
    ):
      return False
    hp: Optional[int] = target.get_hp()
    if hp is None or hp <= 0:
      return False
    buriedness: Optional[int] = target.get_buriedness()
    if buriedness is None:
      return False
    myself = self._agent_info.get_myself()
    if myself is None:
      return False
    # 消防隊は埋まっている人、救急隊は埋まっていない人を対象にする。
    if myself.get_urn() == EntityURN.FIRE_BRIGADE and buriedness == 0:
      return False
    if myself.get_urn() == EntityURN.AMBULANCE_TEAM and buriedness > 0:
      return False
    # 埋没していれば、丸め込みで damage が0になった可能性もあるため対象に残す。
    damage: Optional[int] = target.get_damage()
    if damage is None or damage < 0:
      return False
    if damage == 0 and buriedness == 0:
      return False
    position_entity_id: Optional[EntityID] = target.get_position()
    if position_entity_id is None:
      return False
    position: Optional[Entity] = self._world_info.get_entity(position_entity_id)
    if position is None:
      return False
    # 避難所に到着した人や、救急車で搬送中の人は対象にしない。
    urn: EntityURN = position.get_urn()
    if urn == EntityURN.REFUGE or urn == EntityURN.AMBULANCE_TEAM:
      return False

    return True

  def get_target_entity_id(self) -> Optional[EntityID]:
    # 選んだ対象のIDを、行動を決める側へ渡す。
    return self._result
