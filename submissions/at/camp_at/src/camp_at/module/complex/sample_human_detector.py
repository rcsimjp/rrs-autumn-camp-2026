from typing import Optional, cast

from rcrscore.entities import (
    AmbulanceTeam,
    Civilian,
    Entity,
    EntityID,
    FireBrigade,
    Human,
    Refuge,
    Road,
)
from rcrscore.urn import EntityURN

from adf_core_python.core.agent.communication.message_manager import MessageManager
from adf_core_python.core.agent.communication.standard.bundle.information.message_ambulance_team import (
    MessageAmbulanceTeam,
)
from adf_core_python.core.agent.communication.standard.bundle.information.message_civilian import (
    MessageCivilian,
)
from adf_core_python.core.agent.communication.standard.bundle.information.message_fire_brigade import (
    MessageFireBrigade,
)
from adf_core_python.core.agent.communication.standard.bundle.standard_message_priority import (
    StandardMessagePriority,
)
from adf_core_python.core.agent.communication.standard.utility.apply_to_world_info import (
    apply_to_world_info,
)
from adf_core_python.core.agent.develop.develop_data import DevelopData
from adf_core_python.core.agent.info.agent_info import AgentInfo
from adf_core_python.core.agent.info.scenario_info import ScenarioInfo
from adf_core_python.core.agent.info.world_info import WorldInfo
from adf_core_python.core.agent.module.module_manager import ModuleManager
from adf_core_python.core.component.module.algorithm.clustering import Clustering
from adf_core_python.core.component.module.algorithm.path_planning import PathPlanning
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
        "camp_at.HumanDetector.Clustering",
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
    self.register_sub_module(self._clustering)
    self.register_sub_module(self._path_planning)

    self._result: Optional[EntityID] = None
    self._message_manager: Optional[MessageManager] = None
    # 他の救急隊(AT)が狙っているターゲット (target_id -> (at_id, timestep))
    self._other_at_claims: dict[EntityID, tuple[EntityID, int]] = {}
    # 送信済み市民情報キャッシュ (civ_id -> (hp, buriedness))
    self._broadcasted_civilians: dict[EntityID, tuple[int, int]] = {}
    self._cached_refuges: Optional[list[EntityID]] = None
    # 視覚または通信で死亡・救助完了(Refuge/救急車収容)が確定したID
    self._confirmed_dead: set[EntityID] = set()
    self._confirmed_rescued: set[EntityID] = set()
    self._last_broadcasted_target: Optional[EntityID] = None

    self._logger = get_agent_logger(
      f"{self.__class__.__module__}.{self.__class__.__qualname__}",
      self._agent_info,
    )

  def update_info(self, message_manager: MessageManager) -> HumanDetector:
    super().update_info(message_manager)
    if self.get_count_update_info() > 1:
      return self

    self._message_manager = message_manager
    current_time = self._agent_info.get_time()
    my_id = self._agent_info.get_entity_id()

    # 0. 自分の視覚（Line-of-Sight）による確実な死亡・救助完了の把握
    change_set = self._world_info.get_change_set()
    if change_set is not None:
      for changed_id in change_set.get_changed_entities():
        entity = self._world_info.get_entity(changed_id)
        if isinstance(entity, Human):
          hp = entity.get_hp()
          if hp is not None and hp <= 0:
            self._confirmed_dead.add(changed_id)
          pos_id = entity.get_position()
          if pos_id is not None:
            pos_ent = self._world_info.get_entity(pos_id)
            if pos_ent is not None and pos_ent.get_urn() in (
              EntityURN.REFUGE,
              EntityURN.AMBULANCE_TEAM,
            ):
              self._confirmed_rescued.add(changed_id)

    # 1. 受信メッセージの処理（AT同士の無線通信）
    for msg in message_manager.get_received_message_list():
      # 市民情報の反映
      if isinstance(msg, MessageCivilian):
        cid = msg.get_civilian_entity_id()
        if cid is not None:
          if cid in self._confirmed_dead:
            continue

          apply_to_world_info(self._world_info, msg)
          civ = self._world_info.get_entity(cid)
          if isinstance(civ, Civilian):
            # MessageCivilian仕様: 0はNoneとしてシリアライズされるため明示的に反映
            if msg.get_civilian_buriedness() is None:
              civ.set_buriedness(0)
            if (
              msg.get_civilian_hp() is None
              or msg.get_civilian_hp() <= 0
              or cid in self._confirmed_dead
            ):
              civ.set_hp(0)
              self._confirmed_dead.add(cid)
            if msg.get_civilian_damage() is None:
              civ.set_damage(0)

      # 他の救急隊(AT)の担当ターゲット情報＆埋没SOS情報の受信
      elif isinstance(msg, MessageAmbulanceTeam):
        apply_to_world_info(self._world_info, msg)
        sender_id = msg.get_ambulance_team_entity_id() or msg.get_sender_entity_id()
        target_id = msg.get_target_entity_id()
        action = msg.get_action()
        if sender_id is not None and sender_id != my_id:
          # 送信者の状態確認（救出完了または死亡・埋没SOSを検知）
          sender_ent = self._world_info.get_entity(sender_id)
          if isinstance(sender_ent, Human):
            b_val = msg.get_ambulance_team_buriedness()
            if b_val is not None and b_val > 0:
              sender_ent.set_buriedness(b_val)
            elif b_val is None or b_val == 0:
              sender_ent.set_buriedness(0)
            if sender_ent.get_hp() is not None and sender_ent.get_hp() <= 0:
              self._confirmed_dead.add(sender_id)

          if target_id is not None and action == MessageAmbulanceTeam.ACTION_LOAD:
            if target_id.get_value() != -1:
              self._other_at_claims[target_id] = (sender_id, current_time)
            else:
              # target_id == -1 は担当解除通知
              expired = [
                tid
                for tid, (aid, _) in self._other_at_claims.items()
                if aid == sender_id
              ]
              for tid in expired:
                del self._other_at_claims[tid]

      # 消防隊(FB)の位置情報の受信（掘削現場での連携・先回り待機に活用）
      elif isinstance(msg, MessageFireBrigade):
        apply_to_world_info(self._world_info, msg)

    # 2. 古い担当クレーム（25ステップ超）のパージ
    expired_targets = [
      tid
      for tid, (_, step) in self._other_at_claims.items()
      if current_time - step > 25
    ]
    for tid in expired_targets:
      del self._other_at_claims[tid]

    # 3. 自分の視覚（Line-of-Sight）で見つかった市民の情報をAT仲間に無線送信
    if change_set is not None:
      for changed_id in change_set.get_changed_entities():
        entity = self._world_info.get_entity(changed_id)
        if isinstance(entity, Civilian):
          hp = entity.get_hp() or 0
          buriedness = entity.get_buriedness() or 0
          pos = entity.get_position()
          if pos is not None:
            prev = self._broadcasted_civilians.get(changed_id)
            if prev is None or prev != (hp, buriedness):
              priority = (
                StandardMessagePriority.HIGH
                if (hp <= 0 or buriedness == 0)
                else StandardMessagePriority.NORMAL
              )
              civ_msg = MessageCivilian(
                True,
                entity,
                priority,
                my_id,
              )
              message_manager.add_message(civ_msg)
              self._broadcasted_civilians[changed_id] = (hp, buriedness)

    return self

  def calculate(self) -> HumanDetector:
    # 自身が埋没中の場合は搬送活動不可能。直ちに仲間（FB・AT）へSOSを打電して終了
    myself = self._agent_info.get_myself()
    if isinstance(myself, Human) and (myself.get_buriedness() or 0) > 0:
      self._result = None
      self._broadcast_sos()
      return self

    # 救急車内に市民を乗せている場合はその市民をターゲットとして維持（Refugeへ搬送）
    transport_human: Optional[Human] = self._agent_info.some_one_on_board()
    if transport_human is not None:
      self._result = transport_human.get_entity_id()
      self._broadcast_target(self._result)
      return self

    my_pos = self._agent_info.get_position_entity_id()
    if my_pos is None:
      self._result = None
      return self

    # ★【最優先・スルー防止】足元（同一位置）または直近の救出可能市民の即時ピックアップ
    immediate_target = self._find_immediate_pickup_target(my_pos)
    if immediate_target is not None:
      self._result = immediate_target
      self._broadcast_target(self._result)
      return self

    # 現在のターゲットの妥当性検証
    if self._result is not None:
      if not self._is_valid_human(self._result):
        self._result = None
      else:
        # 非対称近接調停（Asymmetric Proximity Arbitration）：
        # 他のATと競合した場合、自分より優先度の高い（既に現場にいる、または現場に近い）ATがいる場合のみ譲る。
        target_ent = self._world_info.get_entity(self._result)
        if isinstance(target_ent, Human):
          t_pos = target_ent.get_position()
          if t_pos is not None:
            my_id = self._agent_info.get_entity_id()
            my_id_val = my_id.get_value()

            # 1. 現場に既に他のATが到着している場合は譲る
            if any(
              at.get_entity_id() != my_id and at.get_position() == t_pos
              for at in self._world_info.get_entities_of_types([AmbulanceTeam])
            ):
              self._result = None
            else:
              # 2. 無線通信で同じ市民を救急目標にしている他のATと比較
              claimed = self._other_at_claims.get(self._result)
              if claimed is not None:
                other_at_id, _ = claimed
                if other_at_id != my_id:
                  other_at = self._world_info.get_entity(other_at_id)
                  if isinstance(other_at, AmbulanceTeam) and other_at.get_position() is not None:
                    my_dist = self._path_planning.get_distance(my_pos, t_pos)
                    if my_dist == float("inf"):
                      my_dist = self._world_info.get_distance(my_pos, t_pos)
                    o_dist = self._path_planning.get_distance(other_at.get_position(), t_pos)
                    if o_dist == float("inf"):
                      o_dist = self._world_info.get_distance(other_at.get_position(), t_pos)
                    # 相手の方が近い、または同距離でIDが小さい場合に譲る
                    if o_dist < my_dist or (o_dist == my_dist and other_at_id.get_value() < my_id_val):
                      self._result = None

    # 新たなターゲット選定
    if self._result is None:
      self._result = self._select_target()

    self._broadcast_target(self._result)

    return self

  def _broadcast_target(self, target_id: Optional[EntityID]) -> None:
    """自分のターゲットを同部隊(AT)に通知して重複出動を完全防止"""
    if self._message_manager is None:
      return

    # ターゲットがなく、前回も送信していない場合は無駄な無線パケットを送らない
    if target_id is None and self._last_broadcasted_target is None:
      return

    myself = self._agent_info.get_myself()
    if isinstance(myself, AmbulanceTeam):
      my_id = self._agent_info.get_entity_id()
      # ADFのMessageAmbulanceTeamプロトコル仕様: target_entity_idにNoneを渡すと
      # existフラグ0でシリアライズされ、受信側でEntityID(-1)として復元される
      msg = MessageAmbulanceTeam(
        True,
        myself,
        MessageAmbulanceTeam.ACTION_LOAD,
        target_id,
        StandardMessagePriority.HIGH,
        my_id,
      )
      self._message_manager.add_message(msg)
      self._last_broadcasted_target = target_id

  def _broadcast_sos(self) -> None:
    """埋没中の緊急SOS発信（自身の位置・埋没度・HPをFBやATに通知）"""
    if self._message_manager is None:
      return
    myself = self._agent_info.get_myself()
    if isinstance(myself, AmbulanceTeam) and (myself.get_buriedness() or 0) > 0:
      my_id = self._agent_info.get_entity_id()
      msg = MessageAmbulanceTeam(
        True,
        myself,
        MessageAmbulanceTeam.ACTION_REST,
        None,
        StandardMessagePriority.HIGH,
        my_id,
      )
      self._message_manager.add_message(msg)

  def _find_immediate_pickup_target(self, my_pos: EntityID) -> Optional[EntityID]:
    """
    足元（同一エリア/道路）または直接隣接する道路上の救出可能市民を最優先で回収（スルー防止）
    """
    my_pos_ent = self._world_info.get_entity(my_pos)
    if isinstance(my_pos_ent, Refuge):
      return None

    # 1. 足元 (my_pos) にいる buriedness == 0 の生存市民
    co_located: list[Civilian] = []
    for entity in self._world_info.get_entities_of_types([Civilian]):
      cid = entity.get_entity_id()
      if entity.get_position() == my_pos and self._is_valid_human(cid):
        co_located.append(entity)

    if co_located:
      # 最もHPが低く急を要する市民を即時ピックアップ
      co_located.sort(key=lambda c: (c.get_hp() or 10000))
      return co_located[0].get_entity_id()

    # 2. 直近隣接エリア（道路等）にいる歩行中市民 (buriedness == 0)
    if my_pos_ent is not None and hasattr(my_pos_ent, "get_neighbours"):
      neighbours = set(my_pos_ent.get_neighbours() or [])
      adjacent: list[Civilian] = []
      for entity in self._world_info.get_entities_of_types([Civilian]):
        cid = entity.get_entity_id()
        if entity.get_position() in neighbours and self._is_valid_human(cid):
          adjacent.append(entity)
      if adjacent:
        adjacent.sort(key=lambda c: (c.get_hp() or 10000))
        return adjacent[0].get_entity_id()

    return None

  def _get_distance_to_nearest_refuge(self, pos_id: EntityID) -> float:
    """最寄りの避難所(Refuge)までの距離を計算"""
    if self._cached_refuges is None:
      self._cached_refuges = self._world_info.get_entity_ids_of_types([Refuge])
    if not self._cached_refuges:
      return 100000.0

    min_dist = float("inf")
    for r_id in self._cached_refuges:
      d = self._path_planning.get_distance(pos_id, r_id)
      if d == float("inf"):
        d = self._world_info.get_distance(pos_id, r_id)
      if d < min_dist:
        min_dist = d
    return min_dist

  def _has_rescuing_fb(self, civ_pos_id: EntityID) -> bool:
    """市民がいる建物に消防隊(FB)がいるかどうかを判定"""
    for fb in self._world_info.get_entities_of_types([FireBrigade]):
      if fb.get_position() == civ_pos_id:
        return True
    return False

  def _triage_score(
    self, human_id: EntityID, my_position: EntityID, my_cluster_ids: set[EntityID]
  ) -> float:
    target = self._world_info.get_entity(human_id)
    if not isinstance(target, Human):
      return -float("inf")
    hp = target.get_hp() or 10000
    damage = target.get_damage() or 1
    buriedness = target.get_buriedness() or 0
    pos_id = target.get_position()
    if pos_id is None:
      return -float("inf")

    pos_entity = self._world_info.get_entity(pos_id)
    is_on_road = isinstance(pos_entity, Road)

    dist = self._path_planning.get_distance(my_position, pos_id)
    if dist == float("inf"):
      dist = self._world_info.get_distance(my_position, pos_id)

    # 移動ステップ数 (40m/step)
    est_travel_time = dist / 40000.0

    # 1. 埋没市民の先回り待機判定
    wait_time = 0.0
    if buriedness > 0:
      has_fb = self._has_rescuing_fb(pos_id)
      if not has_fb or buriedness > 10:
        return -float("inf")
      wait_time = max(0.0, float(buriedness) - est_travel_time)

    # 2. 余命判定 (TTL) と最寄り避難所搬送時間の合算評価
    ttl = hp / max(1.0, float(damage))
    refuge_dist = self._get_distance_to_nearest_refuge(pos_id)
    est_refuge_time = (refuge_dist / 40000.0) + 2.0
    est_total_rescue_time = est_travel_time + wait_time + est_refuge_time

    # 現場到着後、避難所搬送前に死亡が確実な場合は完全除外
    if ttl < est_total_rescue_time * 0.9:
      return -float("inf")

    # 3. ★【非対称近接調停による完全1対1排他制御・定員1名】
    my_id = self._agent_info.get_entity_id()
    my_id_val = my_id.get_value()
    if human_id in self._other_at_claims:
      other_at_id, _ = self._other_at_claims[human_id]
      if other_at_id != my_id:
        other_at = self._world_info.get_entity(other_at_id)
        if isinstance(other_at, AmbulanceTeam) and other_at.get_position() is not None:
          other_dist = self._path_planning.get_distance(
            other_at.get_position(), pos_id
          )
          if other_dist == float("inf"):
            other_dist = self._world_info.get_distance(other_at.get_position(), pos_id)
          # 相手の方が現場に近い、または同距離で相手のIDが小さい場合は譲る
          if other_dist < dist or (other_dist == dist and other_at_id.get_value() < my_id_val):
            return -float("inf")

    # 4. ★【避難所カルガモ出動防止】クラスタ親和性とエージェント分散タイブレーカー
    cluster_bonus = 6000.0 if pos_id in my_cluster_ids else 0.0
    # 同一避難所からの一斉出動時に異なる市民へ散開させる決定論的オフセット
    tie_breaker = ((human_id.get_value() * 37 + my_id_val) % 19) * 150.0

    # 5. ボーナス・ペナルティ計算
    urgency = 10000.0 / (ttl + 1.0)
    travel_penalty = est_travel_time * 2.0
    wait_penalty = wait_time * 80.0
    # 掘り出し完了市民の即時搬送を最優先
    ready_bonus = 25000.0 if buriedness == 0 else 0.0

    # 道路上を自力歩行中の市民（Heading for a refuge）を即時ピックアップ
    road_pickup_bonus = 6000.0 if (is_on_road and buriedness == 0) else 0.0

    return (
      urgency
      + ready_bonus
      + road_pickup_bonus
      + cluster_bonus
      + tie_breaker
      - travel_penalty
      - wait_penalty
    )

  def _select_target(self) -> Optional[EntityID]:
    my_pos = self._agent_info.get_position_entity_id()
    if my_pos is None:
      return None

    cluster_index: int = self._clustering.get_cluster_index(
      self._agent_info.get_entity_id()
    )
    cluster_entities: list[Entity] = self._clustering.get_cluster_entities(
      cluster_index
    )
    my_cluster_ids = {e.get_entity_id() for e in cluster_entities}

    valid_civilians = [
      entity
      for entity in self._world_info.get_entities_of_types([Civilian])
      if self._is_valid_human(entity.get_entity_id())
    ]

    if not valid_civilians:
      return None

    best_entity = max(
      valid_civilians,
      key=lambda e: self._triage_score(
        e.get_entity_id(), my_pos, my_cluster_ids
      ),
    )

    best_score = self._triage_score(
      best_entity.get_entity_id(), my_pos, my_cluster_ids
    )
    if best_score <= -50000.0:
      return None

    return best_entity.get_entity_id()

  def _is_valid_human(self, target_entity_id: EntityID) -> bool:
    if target_entity_id == self._agent_info.get_entity_id():
      return False

    if target_entity_id in self._confirmed_dead:
      return False
    if target_entity_id in self._confirmed_rescued:
      return False

    target: Optional[Entity] = self._world_info.get_entity(target_entity_id)
    if target is None or not isinstance(target, Human):
      return False
    hp: Optional[int] = target.get_hp()
    if hp is None or hp <= 0:
      return False
    buriedness: Optional[int] = target.get_buriedness()
    if buriedness is None:
      buriedness = 0

    position_entity_id: Optional[EntityID] = target.get_position()
    if position_entity_id is None:
      return False
    position: Optional[Entity] = self._world_info.get_entity(position_entity_id)
    if position is None:
      return False
    urn: EntityURN = position.get_urn()
    if urn == EntityURN.REFUGE or urn == EntityURN.AMBULANCE_TEAM:
      return False

    # 1. 掘出完了(buriedness == 0)は即座に搬送可能（道路上・建物内問わず）
    # 2. 埋没中でもFBが掘っていて浅い(<=15)なら先回り待機ターゲット
    if buriedness > 0:
      if buriedness > 15:
        return False
      if not self._has_rescuing_fb(position_entity_id):
        return False

    return True

  def get_target_entity_id(self) -> Optional[EntityID]:
    return self._result
