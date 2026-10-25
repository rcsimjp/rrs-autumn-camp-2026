from typing import Optional, cast

from rcrscore.entities import Civilian, Entity, EntityID, Human, FireBrigade, AmbulanceTeam
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
                "tmmr.HumanDetector.Clustering",
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
        myself = self._agent_info.get_myself()
        if myself is not None and isinstance(myself, Human):
            hp = myself.get_hp()
            buriedness = myself.get_buriedness()
            if (hp is not None and hp <= 0) or (buriedness is not None and buriedness > 0):
                self._result = None
                return self

        transport_human: Optional[Human] = self._agent_info.some_one_on_board()
        if transport_human is not None:
            self._result = transport_human.get_entity_id()
            return self

        if self._result is not None:
            if not self._is_valid_human(self._result):
                self._result = None

        if self._result is None:
            self._result = self._select_target()

        return self

    def _is_rescued_by_fb(self, target_entity_id: EntityID) -> bool:
        target = self._world_info.get_entity(target_entity_id)
        if target is None or not isinstance(target, Human):
            return False

        buriedness = target.get_buriedness()
        if buriedness is None or buriedness == 0:
            return False

        pos = target.get_position()
        if pos is None:
            return False

        fbs = self._world_info.get_entities_of_types([FireBrigade])
        for fb in fbs:
            if fb.get_position() == pos:
                return True
        return False

    def _is_safely_handled_by_others(self, target_entity_id: EntityID) -> bool:
        target = self._world_info.get_entity(target_entity_id)
        if target is None:
            return False
        target_pos = target.get_position()

        myself = self._agent_info.get_myself()
        if myself is None:
            return False
        my_pos = myself.get_position()
        my_id = myself.get_entity_id()

        ambulances = self._world_info.get_entities_of_types([AmbulanceTeam])
        for amb in ambulances:
            amb_id = amb.get_entity_id()
            if amb_id == my_id:
                continue

            if amb.get_position() == target_pos:
                hp = amb.get_hp()
                if hp is not None and hp <= 0: continue
                buriedness = amb.get_buriedness()
                if buriedness is not None and buriedness > 0: continue

                is_carrying = False
                for civ in self._world_info.get_entities_of_types([Civilian]):
                    if civ.get_position() == amb_id:
                        is_carrying = True
                        break

                if not is_carrying:
                    if my_pos != target_pos:
                        return True
                    else:
                        if amb_id.get_value() < my_id.get_value():
                            return True

        return False

    # --- 修正：動けない救急隊への割り当てを回避するハッシュロジック ---
    def _is_assigned_to_me_globally(self, target_entity_id: EntityID) -> bool:
        ambulances = self._world_info.get_entities_of_types([AmbulanceTeam])
        if not ambulances:
            return True

        ambulances.sort(key=lambda x: x.get_entity_id().get_value())
        num_amb = len(ambulances)

        my_id_value = self._agent_info.get_entity_id().get_value()
        my_index = -1
        for i, amb in enumerate(ambulances):
            if amb.get_entity_id().get_value() == my_id_value:
                my_index = i
                break

        if my_index == -1:
            return True

        # 1. 本来の担当者を決める（固定の分母で計算）
        owner_index = target_entity_id.get_value() % num_amb

        # 2. その担当者が動けないと「知っている」場合、権利を次の人にスライドする（タスクの委譲）
        for _ in range(num_amb):
            owner_amb = ambulances[owner_index]
            is_incapacitated = False

            if isinstance(owner_amb, Human):
                hp = owner_amb.get_hp()
                buriedness = owner_amb.get_buriedness()
                # HP0、または埋没している場合は動けないと判断
                if (hp is not None and hp <= 0) or (buriedness is not None and buriedness > 0):
                    is_incapacitated = True

            if not is_incapacitated:
                break # 動ける担当者が見つかったのでスライド終了

            owner_index = (owner_index + 1) % num_amb

        return owner_index == my_index

    def _get_nearest_entity(self, entities: list[Entity]) -> Optional[EntityID]:
        if not entities:
            return None
        nearest_entity = entities[0]
        nearest_dist = self._world_info.get_distance(
            self._agent_info.get_entity_id(), nearest_entity.get_entity_id()
        )
        for entity in entities[1:]:
            dist = self._world_info.get_distance(
                self._agent_info.get_entity_id(), entity.get_entity_id()
            )
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_entity = entity
        return nearest_entity.get_entity_id()

    def _select_target(self) -> Optional[EntityID]:
        if self._result is not None and self._is_valid_human(self._result):
            return self._result

        cluster_index: int = self._clustering.get_cluster_index(self._agent_info.get_entity_id())
        cluster_entities: list[Entity] = self._clustering.get_cluster_entities(cluster_index)
        myself = self._agent_info.get_myself()

        if myself is not None and myself.get_urn() == EntityURN.AMBULANCE_TEAM:
            # 1. 自分の担当クラスタ内の消防隊救助中市民
            rescue_targets_cluster = [
                e for e in cluster_entities
                if isinstance(e, Civilian) and self._is_rescued_by_fb(e.get_entity_id()) and self._is_valid_human(e.get_entity_id())
            ]
            if rescue_targets_cluster:
                return self._get_nearest_entity(rescue_targets_cluster)

            # 2. マップ全体の消防隊救助中市民（ハッシュ割り当て）
            rescue_targets_world = [
                e for e in self._world_info.get_entities_of_types([Civilian])
                if self._is_rescued_by_fb(e.get_entity_id())
                and self._is_valid_human(e.get_entity_id())
                and self._is_assigned_to_me_globally(e.get_entity_id())
            ]
            if rescue_targets_world:
                return self._get_nearest_entity(rescue_targets_world)

        # 3. 自分の担当クラスタ内の通常の市民
        valid_humans_cluster = [
            e for e in cluster_entities
            if isinstance(e, Civilian) and self._is_valid_human(e.get_entity_id())
        ]
        if valid_humans_cluster:
            return self._get_nearest_entity(valid_humans_cluster)

        # 4. マップ全体の通常の市民（ハッシュ割り当て）
        valid_humans_world = [
            e for e in self._world_info.get_entities_of_types([Civilian])
            if self._is_valid_human(e.get_entity_id())
            and self._is_assigned_to_me_globally(e.get_entity_id())
        ]
        if valid_humans_world:
            return self._get_nearest_entity(valid_humans_world)

        # 5. 【追加】最終フォールバック：自分が暇な場合、ハッシュを完全に無視して残っている市民を助ける
        # これにより、通信が届かずに見捨てられかけている市民も確実にカバーします
        valid_humans_world_all = [
            e for e in self._world_info.get_entities_of_types([Civilian])
            if self._is_valid_human(e.get_entity_id())
        ]
        if valid_humans_world_all:
            return self._get_nearest_entity(valid_humans_world_all)

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

        if myself.get_urn() == EntityURN.AMBULANCE_TEAM:
            if buriedness > 0 and not self._is_rescued_by_fb(target_entity_id):
                return False

            if self._is_safely_handled_by_others(target_entity_id):
                return False

        damage: Optional[int] = target.get_damage()
        if damage is None or damage == 0:
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