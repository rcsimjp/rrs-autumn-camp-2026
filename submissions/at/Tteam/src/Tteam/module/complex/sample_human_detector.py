# from typing import Optional, cast

# from rcrscore.entities import Civilian, Entity, EntityID, Human
# from rcrscore.urn import EntityURN
# # 追加
# from rcrscore.entities import Refuge

# from adf_core_python.core.agent.develop.develop_data import DevelopData
# from adf_core_python.core.agent.info.agent_info import AgentInfo
# from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
# from adf_core_python.core.agent.info.world_info import WorldInfo
# from adf_core_python.core.agent.module.module_manager import ModuleManager
# from adf_core_python.core.component.module.algorithm.clustering import Clustering
# from adf_core_python.core.component.module.complex.human_detector import HumanDetector
# from adf_core_python.core.logger.logger import get_agent_logger



# class SampleHumanDetector(HumanDetector):
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
#     self._clustering: Clustering = cast(
#       Clustering,
#       module_manager.get_module(
#         "myteam.HumanDetector.Clustering",
#         "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
#       ),
#     )
#     self.register_sub_module(self._clustering)

#     self._result: Optional[EntityID] = None
#     self._logger = get_agent_logger(
#       f"{self.__class__.__module__}.{self.__class__.__qualname__}",
#       self._agent_info,
#     )

#   def calculate(self) -> HumanDetector:
#     transport_human: Optional[Human] = self._agent_info.some_one_on_board()
#     if transport_human is not None:
#       self._result = transport_human.get_entity_id()
#       return self

#     if self._result is not None:
#       if not self._is_valid_human(self._result):
#         self._result = None

#     if self._result is None:
#       self._result = self._select_target()

#     return self


#   def _select_target(self) -> Optional[EntityID]:
#       # 現在の目標が有効であれば維持する
#       if self._result is not None and self._is_valid_human(self._result):
#           return self._result

#       # 自分が所属するクラスタの情報を取得する
#       cluster_index: int = self._clustering.get_cluster_index(
#           self._agent_info.get_entity_id()
#       )
#       cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
#           cluster_index
#       )

#       # クラスタ内の有効な民間人IDを集合として保持する
#       cluster_civilian_ids: set[EntityID] = {
#           entity.get_entity_id()
#           for entity in cluster_entities
#           if isinstance(entity, Civilian)
#           and self._is_valid_human(entity.get_entity_id())
#       }

#       # マップ全体から有効な民間人を取得する
#       world_valid_civilians: list[Entity] = [
#           entity
#           for entity in self._world_info.get_entities_of_types([Civilian])
#           if self._is_valid_human(entity.get_entity_id())
#       ]

#       # 対象がいなければ選択できない
#       if not world_valid_civilians:
#           return None

#       # 距離を最優先し、同距離ならクラスタ内の対象を優先する
#       agent_id: EntityID = self._agent_info.get_entity_id()

#       nearest_civilian: Entity = min(
#           world_valid_civilians,
#           key=lambda entity: (
#               self._world_info.get_distance(
#                   agent_id,
#                   entity.get_entity_id(),
#               ),
#               0 if entity.get_entity_id() in cluster_civilian_ids else 1,
#           ),
#       )

#       return nearest_civilian.get_entity_id()



#   # def _select_target(self) -> Optional[EntityID]:
#   #   if self._result is not None and self._is_valid_human(self._result):
#   #     return self._result

#   #   cluster_index: int = self._clustering.get_cluster_index(
#   #     self._agent_info.get_entity_id()
#   #   )
#   #   cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
#   #     cluster_index
#   #   )

#   #   cluster_valid_human_entities: list[Entity] = [
#   #     entity
#   #     for entity in cluster_entities
#   #     if self._is_valid_human(entity.get_entity_id()) and isinstance(entity, Civilian)
#   #   ]
#   #   if len(cluster_valid_human_entities) != 0:
#   #     nearest_human_entity = cluster_valid_human_entities[0]
#   #     nearest_distance = self._world_info.get_distance(
#   #       self._agent_info.get_entity_id(),
#   #       nearest_human_entity.get_entity_id(),
#   #     )
#   #     for entity in cluster_valid_human_entities:
#   #       distance = self._world_info.get_distance(
#   #         self._agent_info.get_entity_id(),
#   #         entity.get_entity_id(),
#   #       )
#   #       if distance < nearest_distance:
#   #         nearest_distance = distance
#   #         nearest_human_entity = entity
#   #     return nearest_human_entity.get_entity_id()

#   #   world_valid_human_entities: list[Entity] = [
#   #     entity
#   #     for entity in self._world_info.get_entities_of_types([Civilian])
#   #     if self._is_valid_human(entity.get_entity_id())
#   #   ]
#   #   if len(world_valid_human_entities) != 0:
#   #     nearest_human_entity = world_valid_human_entities[0]
#   #     nearest_distance = self._world_info.get_distance(
#   #       self._agent_info.get_entity_id(),
#   #       nearest_human_entity.get_entity_id(),
#   #     )
#   #     for entity in world_valid_human_entities:
#   #       distance = self._world_info.get_distance(
#   #         self._agent_info.get_entity_id(),
#   #         entity.get_entity_id(),
#   #       )
#   #       if distance < nearest_distance:
#   #         nearest_distance = distance
#   #         nearest_human_entity = entity
#   #     return nearest_human_entity.get_entity_id()

#   #   return None

#   AGENT_CAN_MOVE = 40000.0

#   def _is_valid_human(self, target_entity_id: EntityID) -> bool:
#       """
#       指定された EntityID の人間が有効なターゲットかどうかを判定する。

#       Args:
#           target_entity_id (EntityID): 判定する人間の EntityID。

#       Returns:
#           bool: 有効なターゲットであれば True、そうでなければ False。
#       """

#       # EntityID からエンティティを取得
#       target: Optional[Entity] = self._world_info.get_entity(target_entity_id)
#       if target is None:
#           return False

#       # Human であるか確認
#       if not isinstance(target, Human):
#           return False

#       # HP が 0 より大きいか確認
#       hp: Optional[int] = target.get_hp()
#       if hp is None or hp <= 0:
#           return False

#       # ダメージが 0 より大きいか確認
#       damage: Optional[int] = target.get_damage()
#       if damage is None or damage == 0:
#           return False

#       # 位置情報の EntityID を取得
#       position_entity_id: Optional[EntityID] = target.get_position()
#       if position_entity_id is None:
#           return False

#       # 位置情報のエンティティを取得
#       position: Optional[Entity] = self._world_info.get_entity(
#           position_entity_id
#       )
#       if position is None:
#           return False

#       # 避難所または救急隊に位置する人間は除外
#       urn: EntityURN = position.get_urn()
#       if urn == EntityURN.REFUGE or urn == EntityURN.AMBULANCE_TEAM:
#           return False

#       # 最寄りの避難所の ID を取得
#       refuge_ids = self._world_info.get_entity_ids_of_types([Refuge])

#       # 避難所が存在しない場合は無効なターゲットとする
#       if not refuge_ids:
#           return False

#       nearest_refuge: EntityID = min(
#           refuge_ids,
#           key=lambda refuge_id: self._world_info.get_distance(
#               target_entity_id, refuge_id
#           ),
#       )

#       # 生存時間を計算
#       life_time = self._life_time(hp, damage)

#       # エージェントから対象までの移動時間
#       agent_position_id = self._agent_info.get_position_entity_id()
#       if agent_position_id is None:
#           return False

#       agent_to_civilian = (
#           self._world_info.get_distance(
#               agent_position_id, target_entity_id
#           )
#           / self.AGENT_CAN_MOVE
#       )

#       # 対象から最寄りの避難所までの移動時間
#       civilian_to_refuge = (
#           self._world_info.get_distance(
#               target_entity_id, nearest_refuge
#           )
#           / self.AGENT_CAN_MOVE
#       )

#       # デバッグログ
#       self._logger.info(
#           f"life_time: {life_time}, "
#           f"agent_to_civilian: {agent_to_civilian}, "
#           f"civilian_to_refuge: {civilian_to_refuge}"
#       )

#       # 生存時間内に到着・搬送できない場合は除外
#       if life_time < agent_to_civilian + civilian_to_refuge:
#           return False

#       # 埋没度を確認
#       buriedness: Optional[int] = target.get_buriedness()
#       if buriedness is None or buriedness < 0:
#           return False

#       # 救急隊は埋没している人間を対象外とする
#       myself = self._agent_info.get_myself()
#       if myself is None:
#           return False

#       if (
#           myself.get_urn() == EntityURN.AMBULANCE_TEAM
#           and buriedness > 0
#       ):
#           return False

#       # 全ての条件を満たせば有効なターゲット
#       return True

#   # def _is_valid_human(self, target_entity_id: EntityID) -> bool:
#   #   target: Optional[Entity] = self._world_info.get_entity(target_entity_id)
#   #   if target is None:
#   #     return False
#   #   if not isinstance(target, Human):
#   #     return False
#   #   hp: Optional[int] = target.get_hp()
#   #   if hp is None or hp <= 0:
#   #     return False
#   #   buriedness: Optional[int] = target.get_buriedness()
#   #   if buriedness is None:
#   #     return False
#   #   myself = self._agent_info.get_myself()
#   #   if myself is None:
#   #     return False
#   #   if myself.get_urn() == EntityURN.FIRE_BRIGADE and buriedness == 0:
#   #     return False
#   #   if myself.get_urn() == EntityURN.AMBULANCE_TEAM and buriedness > 0:
#   #     return False
#   #   damage: Optional[int] = target.get_damage()
#   #   if damage is None or damage == 0:
#   #     return False
#   #   position_entity_id: Optional[EntityID] = target.get_position()
#   #   if position_entity_id is None:
#   #     return False
#   #   position: Optional[Entity] = self._world_info.get_entity(position_entity_id)
#   #   if position is None:
#   #     return False
#   #   urn: EntityURN = position.get_urn()
#   #   if urn == EntityURN.REFUGE or urn == EntityURN.AMBULANCE_TEAM:
#   #     return False

#   #   return True

#   def get_target_entity_id(self) -> Optional[EntityID]:
#     return self._result


#   # LifeTime用
#   D_NOISE = 0.1
#   D_K_B = 0.00025
#   D_K_C = 0.00035
#   D_L_B = 0.01
#   D_L_C = 0.01

#   # 生存時間を計算するメソッド
#   def _life_time(self, hp, damage):
#       time = 0
#       while (hp > 0) :
#           d = damage
#           damage += self._calc_damage_bury(d)
#           damage += self._calc_damage_collapse(d)
#           # damage += self._calc_damage_fire(d)
#           hp -= damage
#           time += 1
#       return time

#   # 埋没度
#   def _calc_damage_bury(self, d):
#       return (self.D_K_B * d * d) + self.D_L_B + self.D_NOISE

#   # 倒壊？
#   def _calc_damage_collapse(self, d):
#       return (self.D_K_C * d * d) + self.D_L_C + self.D_NOISE


from typing import Optional, cast

from adf_core_python.core.agent.develop.develop_data import DevelopData
from adf_core_python.core.agent.info.agent_info import AgentInfo
from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
from adf_core_python.core.agent.info.world_info import WorldInfo
from adf_core_python.core.agent.module.module_manager import ModuleManager
from adf_core_python.core.component.module.algorithm.clustering import Clustering
from adf_core_python.core.component.module.complex.human_detector import HumanDetector
from adf_core_python.core.logger.logger import get_agent_logger
from rcrscore.entities import Civilian, Entity, EntityID, Human, Refuge
from rcrscore.urn import EntityURN


class SampleHumanDetector(HumanDetector):
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
    self._clustering: Clustering = cast(
      Clustering,
      module_manager.get_module(
        "tteam.HumanDetector.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )
    self.register_sub_module(self._clustering)

    self._result: Optional[EntityID] = None
    # 前ステップの埋没度を保持する辞書
    self._previous_buriedness: dict[EntityID, int] = {}

    self._logger = get_agent_logger(
      f"{self.__class__.__module__}.{self.__class__.__qualname__}",
      self._agent_info,
    )

  def calculate(self) -> HumanDetector:
    transport_human: Optional[Human] = self._agent_info.some_one_on_board()
    if transport_human is not None:
      self._result = transport_human.get_entity_id()
      self._update_previous_buriedness()
      return self

    # 既存の目標が有効であれば維持する（掘り起こし中であってもターゲットを変更しない）
    if self._result is not None:
      if not self._is_valid_target(self._result):
        self._result = None

    # 目標がなければ新しく選択する
    if self._result is None:
      self._result = self._select_target()

    # 現在のステップの埋没度を次回比較用に保存
    self._update_previous_buriedness()
    return self

  def _update_previous_buriedness(self) -> None:
    self._previous_buriedness.clear()
    for entity in self._world_info.get_entities_of_types([Civilian]):
      if isinstance(entity, Human):
        b = entity.get_buriedness()
        if b is not None:
          self._previous_buriedness[entity.get_entity_id()] = b

  def _select_target(self) -> Optional[EntityID]:
      candidates = []

      for entity in self._world_info.get_entities_of_types([Civilian]):
          entity_id = entity.get_entity_id()

          # 基本的なターゲットとしての有効性チェック
          if not self._is_valid_target(entity_id):
              continue

          # 1ステップ前と比較して埋没度が減少している（消防隊によって救助されている）か確認
          prev_buriedness = self._previous_buriedness.get(entity_id)
          human_entity = cast(Human, entity)
          current_buriedness = human_entity.get_buriedness()

          if prev_buriedness is None or current_buriedness is None:
              continue

          # 前ステップより埋没度が減っている場合を候補とする
          if current_buriedness < prev_buriedness:
              candidates.append((human_entity, current_buriedness))

      if not candidates:
          return None

      # 埋没度が少ない順（昇順）にソートする
      candidates.sort(key=lambda x: x[1])

      return candidates[0][0].get_entity_id()

  AGENT_CAN_MOVE = 40000.0

  def _is_valid_target(self, target_entity_id: EntityID) -> bool:
      """
      指定された EntityID の人間がターゲットとして維持可能か、または基本条件を満たしているかを判定する。
      """
      target: Optional[Entity] = self._world_info.get_entity(target_entity_id)
      if target is None:
          return False

      if not isinstance(target, Human):
          return False

      hp: Optional[int] = target.get_hp()
      if hp is None or hp <= 0:
          return False

      damage: Optional[int] = target.get_damage()
      if damage is None or damage == 0:
          return False

      position_entity_id: Optional[EntityID] = target.get_position()
      if position_entity_id is None:
          return False

      position: Optional[Entity] = self._world_info.get_entity(
          position_entity_id
      )
      if position is None:
          return False

      urn: EntityURN = position.get_urn()
      if urn == EntityURN.REFUGE or urn == EntityURN.AMBULANCE_TEAM:
          return False

      refuge_ids = self._world_info.get_entity_ids_of_types([Refuge])
      if not refuge_ids:
          return False

      nearest_refuge: EntityID = min(
          refuge_ids,
          key=lambda refuge_id: self._world_info.get_distance(
              target_entity_id, refuge_id
          ),
      )

      life_time = self._life_time(hp, damage)

      agent_position_id = self._agent_info.get_position_entity_id()
      if agent_position_id is None:
          return False

      agent_to_civilian = (
          self._world_info.get_distance(
              agent_position_id, target_entity_id
          )
          / self.AGENT_CAN_MOVE
      )

      civilian_to_refuge = (
          self._world_info.get_distance(
              target_entity_id, nearest_refuge
          )
          / self.AGENT_CAN_MOVE
      )

      if life_time < agent_to_civilian + civilian_to_refuge:
          return False

      buriedness: Optional[int] = target.get_buriedness()
      if buriedness is None or buriedness < 0:
          return False

      # 救助途中（buriedness > 0）であっても一度選んだターゲットを維持できるようにするため、
      # 救急隊の buriedness > 0 による除外条件は入れない。

      return True

  def get_target_entity_id(self) -> Optional[EntityID]:
    return self._result

  # LifeTime用
  D_NOISE = 0.1
  D_K_B = 0.00025
  D_K_C = 0.00035
  D_L_B = 0.01
  D_L_C = 0.01

  def _life_time(self, hp, damage):
      time = 0
      while (hp > 0) :
          d = damage
          damage += self._calc_damage_bury(d)
          damage += self._calc_damage_collapse(d)
          hp -= damage
          time += 1
      return time

  def _calc_damage_bury(self, d):
      return (self.D_K_B * d * d) + self.D_L_B + self.D_NOISE

  def _calc_damage_collapse(self, d):
      return (self.D_K_C * d * d) + self.D_L_C + self.D_NOISE
