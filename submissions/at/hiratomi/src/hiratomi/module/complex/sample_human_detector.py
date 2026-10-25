from typing import Optional, cast

from rcrscore.entities import Civilian, Entity, EntityID, Human
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
        "hiratomi.HumanDetector.Clustering",
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

    if self._result is None:
      self._result = self._select_target()

    self._logger.info(f"target={self._result}")
    return self

  def _select_target(self) -> Optional[EntityID]:
    # 既に有効なターゲットがいる場合はそのまま維持
    if self._result is not None and self._is_valid_human(self._result):
      return self._result

    # 世界全体から有効な市民（Civilian）を取得
    world_valid_human_entities: list[Entity] = [
      entity
      for entity in self._world_info.get_entities_of_types([Civilian])
      if self._is_valid_human(entity.get_entity_id())
    ]
    
    # 世界全体の候補から最も距離が近い対象を選択
    if len(world_valid_human_entities) != 0:
      nearest_human_entity = world_valid_human_entities[0]
      nearest_distance = self._world_info.get_distance(
        self._agent_info.get_entity_id(),
        nearest_human_entity.get_entity_id(),
      )
      for entity in world_valid_human_entities:
        distance = self._world_info.get_distance(
          self._agent_info.get_entity_id(),
          entity.get_entity_id(),
        )
        if distance < nearest_distance:
          nearest_distance = distance
          nearest_human_entity = entity
      return nearest_human_entity.get_entity_id()

    return None

  def _is_valid_human(self, target_entity_id: EntityID) -> bool:
    def reject(reason: str) -> bool:
        self._logger.info(f"reject {target_entity_id}: {reason}")
        return False

    target: Optional[Entity] = self._world_info.get_entity(target_entity_id)
    if target is None:
        return reject("entity None")
    if not isinstance(target, Human):
        return reject("not Human")
    hp = target.get_hp()
    if hp is None or hp <= 0:
        return reject(f"hp={hp}")
    buriedness = target.get_buriedness()
    if buriedness is None:
        return reject("buriedness None")
    myself = self._agent_info.get_myself()
    if myself is None:
        return reject("myself None")
    if myself.get_urn() == EntityURN.FIRE_BRIGADE and buriedness == 0:
        return reject("FB & buriedness 0")
    if myself.get_urn() == EntityURN.AMBULANCE_TEAM and buriedness > 10:
        return reject(f"AT & buriedness={buriedness}")
    damage = target.get_damage()
    if damage is None:
        return reject(f"damage={damage}")
    position_entity_id = target.get_position()
    if position_entity_id is None:
        return reject("position None")
    position = self._world_info.get_entity(position_entity_id)
    if position is None:
        return reject("position entity None")
    urn = position.get_urn()
    if urn == EntityURN.REFUGE or urn == EntityURN.AMBULANCE_TEAM:
        return reject(f"position urn={urn}")
    return True

  def get_target_entity_id(self) -> Optional[EntityID]:
    return self._result
