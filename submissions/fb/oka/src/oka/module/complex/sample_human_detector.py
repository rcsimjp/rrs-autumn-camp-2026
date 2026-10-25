from typing import Optional, cast

# --- 変更点1: FireBrigade, PoliceForce, AmbulanceTeam をインポートに追加 ---
from rcrscore.entities import AmbulanceTeam, Civilian, Entity, EntityID, FireBrigade, Human, PoliceForce
from rcrscore.urn import EntityURN

from adf_core_python.core.agent.develop.develop_data import DevelopData
from adf_core_python.core.agent.info.agent_info import AgentInfo
from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
from adf_core_python.core.agent.info.world_info import WorldInfo
from adf_core_python.core.agent.module.module_manager import ModuleManager
from adf_core_python.core.component.module.algorithm.clustering import Clustering
from adf_core_python.core.component.module.complex.human_detector import HumanDetector
from adf_core_python.core.logger.logger import get_agent_logger


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
        "oka.HumanDetector.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )
    self.register_sub_module(self._clustering)

    self._result: Optional[EntityID] = None
    self._logger = get_agent_logger(
      f"{self.__class__.__module__}.{self.__class__.__qualname__}",
      self._agent_info,
    )

  def calculate(self) -> HumanDetector:
    transport_human: Optional[Human] = self._agent_info.some_one_on_board()
    if transport_human is not None:
      self._result = transport_human.get_entity_id()
      return self

    if self._result is not None:
      if not self._is_valid_human(self._result):
        self._result = None

    self._result = self._select_target()
    return self

  # 追加
  def _calculate_target_score(self, entity: Entity) -> float:
    distance = self._world_info.get_distance(
      self._agent_info.get_entity_id(),
      entity.get_entity_id(),
    )
    hp = entity.get_hp()
    damage = entity.get_damage()
    
    # 追加: 埋没度の取得
    buriedness = entity.get_buriedness()
    if buriedness is None:
        buriedness = 0
    
    if hp is None:
        time_to_death = float('inf')
    elif damage is None or damage == 0:
        time_to_death = 1000.0
    else:
        time_to_death = hp / damage
        
    # 追加1: 足切り判定（移動にかかる推定ターン＋埋没度 が猶予時間を超える場合は諦める）
    # ※ distance をターン数に換算する係数（一旦仮に 30000.0）調整したい
    estimated_turns = (distance / 30000.0) + buriedness
    if time_to_death < estimated_turns:
        return float('inf') # 助け切る前に死んでしまうため対象から除外

    # 距離が近く、死期が近いほどスコアを小さく（優先度を高く）する
    alpha = 1.0
    beta = 50.0 
    gamma = 20.0  # 追加: 埋没度（救出の手間）に対するペナルティの重み

    #gammaを計算式に追加する
    base_score = (alpha * distance) + (beta * time_to_death) + (gamma * buriedness)

    if not isinstance(entity, Civilian):
        base_score *= 0.1
        
    return base_score
  
  def _select_target(self) -> Optional[EntityID]:
    cluster_index: int = self._clustering.get_cluster_index(
      self._agent_info.get_entity_id()
    )
    cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
      cluster_index
    )

    # --- クラスタ内の探索 ---
    cluster_valid_human_entities: list[Entity] = [
      entity
      for entity in cluster_entities
      # --- 変更点4: isinstance(entity, Civilian) を Human に変更 ---
      if self._is_valid_human(entity.get_entity_id()) and isinstance(entity, Human)
    ]
    if len(cluster_valid_human_entities) != 0:
      best_target = cluster_valid_human_entities[0]
      best_score = self._calculate_target_score(best_target)
      
      for entity in cluster_valid_human_entities:
        score = self._calculate_target_score(entity)
        if score < best_score:
          best_score = score
          best_target = entity
      return best_target.get_entity_id()

    # --- ワールド全体の探索 ---
    world_valid_human_entities: list[Entity] = [
      entity
      # --- 変更点5: Civilianだけでなく各エージェントも探索対象に含める ---
      for entity in self._world_info.get_entities_of_types([Civilian, FireBrigade, PoliceForce, AmbulanceTeam])
      if self._is_valid_human(entity.get_entity_id())
    ]
    if len(world_valid_human_entities) != 0:
      best_target = world_valid_human_entities[0]
      best_score = self._calculate_target_score(best_target)
      
      for entity in world_valid_human_entities:
        score = self._calculate_target_score(entity)
        if score < best_score:
          best_score = score
          best_target = entity
      return best_target.get_entity_id()

    return None

  def _is_valid_human(self, target_entity_id: EntityID) -> bool:
    target: Optional[Entity] = self._world_info.get_entity(target_entity_id)
    if target is None:
      return False
    if not isinstance(target, Human):
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
    if myself.get_urn() == EntityURN.FIRE_BRIGADE and buriedness == 0:
      return False
    if myself.get_urn() == EntityURN.AMBULANCE_TEAM and buriedness > 0:
      return False
      
    damage: Optional[int] = target.get_damage()
    # --- 変更点6: 「ダメージ0」でも「埋没している（Buriedness > 0）」なら足切りしないように修正 ---
    if (damage is None or damage == 0) and buriedness == 0:
      return False
      
    position_entity_id: Optional[EntityID] = target.get_position()
    if position_entity_id is None:
      return False
    position: Optional[Entity] = self._world_info.get_entity(position_entity_id)
    if position is None:
      return False
    urn: EntityURN = position.get_urn()
    if urn == EntityURN.REFUGE or urn == EntityURN.AMBULANCE_TEAM:
      return False

    return True

  def get_target_entity_id(self) -> Optional[EntityID]:
    return self._result