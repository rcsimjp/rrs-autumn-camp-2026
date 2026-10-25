from typing import Optional, cast

from rcrscore.entities import AmbulanceTeam, Area, Building, Civilian, EntityID, FireBrigade, Human, Refuge

from adf_core_python.core.agent.communication.message_manager import MessageManager
from adf_core_python.core.agent.communication.standard.bundle.information.message_fire_brigade import (
  MessageFireBrigade,
)
from adf_core_python.core.agent.communication.standard.bundle.standard_message import (
  StandardMessage,
)
from adf_core_python.core.agent.communication.standard.bundle.standard_message_priority import (
  StandardMessagePriority,
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

from src.myteam.communication.rescue_report import create_civilian_status_message
from src.myteam.module.complex.sample_human_detector import SampleHumanDetector


# 次に調べに行く建物を選ぶクラス。移動や救助そのものは別の処理が担当する。
# 建物内を確認し、救助対象の埋没者がいなければ探索済みとして記憶する。
class SampleSearch(Search):
  # 5は「探索完了」を表すmyteam独自の約束。ADF標準の定義ではない。
  # 本来は消防隊の行動を伝えるaction欄を、完了通知の目印として転用している。
  # この約束を知らないコードには、5が探索完了という意味だとは伝わらない。
  ACTION_SEARCH_COMPLETED = 5

  # 起動時に一度だけ呼ばれる。記憶用の集合と、区域分割・経路計算を用意する。
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

    # いま担当している区域で、まだ調べる必要がある建物。
    self._unreached_building_ids: set[EntityID] = set()
    # 自分の確認と通信を合わせた探索済み建物。担当区域の外の建物も保存する。
    self._searched_building_ids: set[EntityID] = set()
    # 上の集合のうち、ほかの消防隊の通信で知った建物だけを別にも記録する。
    self._received_searched_building_ids: set[EntityID] = set()
    # 現在探索している区域。最初の担当から始め、完了するたびに切り替える。
    self._current_cluster_index: Optional[int] = None
    # 全対象建物が探索済みになった区域の番号。完了した区域へ戻らないために保持する。
    # 現在のKMeansは起動時に区域を作り、その後は区域分割を変更しない。
    self._searched_cluster_ids: set[int] = set()
    # 通信開始前などに作った市民の状態報告・探索完了通知を順番に保管する。
    self._pending_search_reports: list[StandardMessage] = []
    # 同じ搬送待ち市民を毎ステップ報告しないための記録。
    self._reported_transport_civilian_ids: set[EntityID] = set()
    # 次の探索先の建物ID。行き先がなければNone。
    self._result: Optional[EntityID] = None

    # 地図を区域（クラスタ）に分け、自分の担当区域を調べるための部品。
    self._clustering: Clustering = cast(
      Clustering,
      module_manager.get_module(
        "myteam.Search.Clustering",
        "adf_core_python.implement.module.algorithm.k_means_clustering.KMeansClustering",
      ),
    )

    # 道路を通った場合の距離を求める部品。直線距離で探索先を選ばないために使う。
    self._path_planning: PathPlanning = cast(
      PathPlanning,
      module_manager.get_module(
        "myteam.Search.PathPlanning",
        "src.camp_default_2026.cached_path_planning.CachedPathPlanning",
      ),
    )

    self._logger = get_agent_logger(
      f"{self.__class__.__module__}.{self.__class__.__qualname__}",
      self._agent_info,
    )

    # このSearchの準備や情報更新に合わせて、上の2つの部品も更新してもらう。
    self.register_sub_module(self._clustering)
    self.register_sub_module(self._path_planning)

  # 毎ステップ、移動先を選ぶ前に記憶を更新する。救助中でも呼ばれる。
  def update_info(self, message_manager: MessageManager) -> Search:
    super().update_info(message_manager)
    # 同じステップに複数回呼ばれても、通知の処理は1回だけにする。
    if self.get_count_update_info() > 1:
      return self

    self._receive_completed_buildings(message_manager)  # 1. 他の隊の報告を記憶する。
    self._report_searched_building()                  # 2. 市民を報告し、建物を確認する。
    self._send_pending_reports(message_manager)       # 3. 保留中の報告を送る。
    # 4. 現在の区域が完了したら次の区域へ切り替え、未探索建物を候補にする。
    # 区域を切り替えても、探索済みの建物・区域の記憶は消さない。
    self._unreached_building_ids = self._get_search_targets()

    return self

  # 残っている候補のうち、経路距離が最も近い建物を次の行き先にする。
  def calculate(self) -> Search:
    position = self._agent_info.get_position_entity_id()
    if position is None:
      # 自分の現在地が分からなければ、行き先を決められない。
      self._result = None
      return self

    nearest_building_id: Optional[EntityID] = None
    nearest_distance = float("inf")  # 最初は無限大にして、最初の到達可能候補を選べるようにする。
    # ID順に調べるので、距離が同じなら小さいIDの建物に決まる。
    for building_id in sorted(self._unreached_building_ids, key=lambda id: id.get_value()):
      # 他の人がいる現在の建物を、その場での探索移動の目的地にしない。
      if building_id == position:
        continue
      distance = self._path_planning.get_distance(position, building_id)
      # 経路がなければ距離は無限大になり、この比較を通らない。
      if distance < nearest_distance:
        nearest_building_id = building_id
        nearest_distance = distance
    # 候補がない場合や、どの候補にも経路がない場合はNoneになる。
    self._result = nearest_building_id
    return self

  # 行動を決める側が、このIDを受け取って移動処理に渡す。
  def get_target_entity_id(self) -> Optional[EntityID]:
    return self._result

  # 受信した報告の中から「消防隊による探索完了報告」だけを取り出す。
  def _receive_completed_buildings(self, message_manager: MessageManager) -> None:
    for message in message_manager.get_received_message_list():
      if not isinstance(message, MessageFireBrigade):
        continue
      # 通常の位置報告だけでは探索完了とみなさない。
      if message.get_action() != self.ACTION_SEARCH_COMPLETED:
        continue
      sender_id = message.get_sender_entity_id()
      sender = self._world_info.get_entity(sender_id)
      # 送信者が、把握している消防隊であることを確認する。
      if not isinstance(sender, FireBrigade):
        continue
      if message.get_fire_brigade_entity_id() != sender_id:
        continue
      building_id = message.get_target_entity_id()
      # 「完了した建物」と「確認した隊員の位置」が同じ報告だけを受け付ける。
      # 位置は報告を作った時点のもので、受信時には隊員が移動済みでもよい。
      if building_id is None or message.get_fire_brigade_position() != building_id:
        continue
      building = self._world_info.get_entity(building_id)
      if isinstance(building, Building) and not isinstance(building, Refuge):
        # 担当区域外でも保存する。後で担当区域が変わったときにも利用する。
        self._received_searched_building_ids.add(building_id)
        self._searched_building_ids.add(building_id)

  # 建物の確認は「今回見えた人を集める→市民を報告→完了判定→完了を記録」の順。
  # 探索完了は建物の確認が済んだという意味で、全員の救出完了とは限らない。
  def _report_searched_building(self) -> None:
    myself = self._agent_info.get_myself()
    if not isinstance(myself, FireBrigade):
      return
    hp = myself.get_hp()
    # 死亡・埋没中の隊員からは、探索完了の報告を作らない。
    if hp is None or hp <= 0 or myself.get_buriedness() != 0:
      return
    building_id = self._agent_info.get_position_entity_id()
    if building_id is None or building_id in self._searched_building_ids:
      # 現在地が不明、または報告済み・受信済みの建物なら処理を終える。
      return
    building = self._world_info.get_entity(building_id)
    if not isinstance(building, Building) or isinstance(building, Refuge):
      return
    # 外から見ただけでは完了にせず、建物内で今回知覚した場合だけ確認する。
    changed_ids = self._world_info.get_change_set().get_changed_entities()
    if building_id not in changed_ids:
      return

    occupants = self._get_visible_building_occupants(building_id)
    for human in occupants:
      # 埋没者がほかに残っていても、搬送待ち市民の報告は先に行う。
      self._report_transport_civilian(myself, human)

    if any(self._needs_rescue_or_confirmation(human) for human in occupants):
      return
    # 救助・確認が必要な人が残っていなければ、探索完了を記録する。
    self._mark_building_searched(myself, building_id)

  # 現在の建物内で今回知覚した人だけを集める。自分自身は含めない。
  def _get_visible_building_occupants(self, building_id: EntityID) -> list[Human]:
    occupants: list[Human] = []
    changed_ids = self._world_info.get_change_set().get_changed_entities()
    # 過去の位置情報だけでは「まだ建物内にいる」と判断しない。
    # すでに移動した救急隊などの古い記憶が、探索完了を妨げるのを防ぐ。
    for entity_id in changed_ids:
      human = self._world_info.get_entity(entity_id)
      if not isinstance(human, Human):
        continue
      if human.get_entity_id() == self._agent_info.get_entity_id() or human.get_position() != building_id:
        continue
      occupants.append(human)
    return occupants

  # この人が残っているために、建物の探索完了を保留すべきかを判定する。
  def _needs_rescue_or_confirmation(self, human: Human) -> bool:
    # Detectorと同じ時刻で隊員を対象外にし、探索済み建物の再訪・区域での足止めを防ぐ。
    if (
      isinstance(human, (FireBrigade, AmbulanceTeam))
      and self._agent_info.get_time() >= SampleHumanDetector.RESCUE_AGENT_TIME_LIMIT
    ):
      return False
    hp = human.get_hp()
    buriedness = human.get_buriedness()
    # 生存した埋没者、または生死・埋没度が不明で確認が必要な人がいれば保留する。
    # 埋没度0の市民はdamageが丸めで0になっていても、探索完了を妨げない。
    return (hp is None or hp > 0) and (buriedness is None or buriedness > 0)

  # 生存していて、掘り出し済み・負傷中の市民を救急隊へ報告する。
  def _report_transport_civilian(self, myself: FireBrigade, human: Human) -> None:
    if not isinstance(human, Civilian):
      return
    hp = human.get_hp()
    damage = human.get_damage()
    if hp is None or hp <= 0 or human.get_buriedness() != 0:
      return
    if damage is None or damage <= 0:
      return
    civilian_id = human.get_entity_id()
    if civilian_id in self._reported_transport_civilian_ids:
      return
    self._pending_search_reports.append(create_civilian_status_message(myself, human))
    self._reported_transport_civilian_ids.add(civilian_id)

  # 確認した建物を記憶し、探索完了の通知を用意する（救出完了の通知ではない）。
  def _mark_building_searched(self, myself: FireBrigade, building_id: EntityID) -> None:
    self._searched_building_ids.add(building_id)
    # 標準の消防隊メッセージを借りて、「この建物は探索済み」と知らせる。
    self._pending_search_reports.append(
      MessageFireBrigade(
        is_wireless_message=True,                 # 声ではなく無線で送る。
        fire_brigade=myself,                       # 確認した隊員と、その時点の位置。
        action=self.ACTION_SEARCH_COMPLETED,      # 独自の目印5。移動や救助の命令ではない。
        target_entity_id=building_id,              # 探索が完了した建物のID。
        priority=StandardMessagePriority.NORMAL,   # 通信上の優先度は通常。
        sender_entity_id=myself.get_entity_id(),   # この報告を作った隊員のID。
      )
    )

  # 作成済みの報告を、ADFの送信キューへ渡す。実際の無線送信はADFが担当する。
  def _send_pending_reports(self, message_manager: MessageManager) -> None:
    # チャンネル購読が有効になるまで通知を保持し、開始直後の送信漏れを避ける。
    ignore_until = self._scenario_info.get_value("kernel.agents.ignoreuntil", 0)
    if self._agent_info.get_time() <= ignore_until + 1:
      return
    if self._scenario_info.get_value("comms.channels.count", 1) <= 1:
      # チャンネル0は声用なので、無線チャンネルがなければ保留を続ける。
      return
    # 通信量を抑えるため、保留中の通知は1ステップに1件ずつ送る。
    if self._pending_search_reports:
      # 先頭の通知を渡したら保留から削除する。受信確認や再送は実装していない。
      message_manager.add_message(self._pending_search_reports.pop(0))

  # 区域が完了したら、未完了建物が多い区域を手伝う。同数なら中心が近い区域へ移る。
  def _get_search_targets(self) -> set[EntityID]:
    if self._current_cluster_index is None:
      # 最初の一度だけ、起動時に割り当てられた担当区域を使う。
      self._current_cluster_index = self._clustering.get_cluster_index(
        self._agent_info.get_entity_id()
      )

    remaining_buildings: dict[int, set[EntityID]] = {}
    for cluster_index in range(self._clustering.get_cluster_number()):
      if cluster_index in self._searched_cluster_ids:
        continue
      building_ids = {
        entity.get_entity_id()
        for entity in self._clustering.get_cluster_entities(cluster_index)
        if isinstance(entity, Building) and not isinstance(entity, Refuge)
      }
      # 集合A <= 集合Bは「Aの全要素がBに入っているか」という意味。
      # つまり、その区域の全建物が探索済みなら区域全体を完了にする。
      # 避難所しかない区域など、対象建物が0件の区域も完了扱いになる。
      if building_ids <= self._searched_building_ids:
        self._searched_cluster_ids.add(cluster_index)
        self._logger.debug(
          f"search cluster completed: {cluster_index}",
          time=self._agent_info.get_time(),
        )
      else:
        remaining_buildings[cluster_index] = building_ids - self._searched_building_ids

    # いまの区域が未完了なら探索を続ける。毎回別の区域を選び直さない。
    if self._current_cluster_index in remaining_buildings:
      return remaining_buildings[self._current_cluster_index]
    if not remaining_buildings:
      # 全区域が完了したときだけ、探索する区域がなくなる。
      return set()

    position_id = self._agent_info.get_position_entity_id()
    position = self._world_info.get_entity(position_id) if position_id is not None else None
    if not isinstance(position, Area):
      return set()
    x, y = position.get_location()
    if x is None or y is None:
      return set()

    # 未完了建物数が多い順→中心までの直線距離が近い順→区域番号順で選ぶ。
    # minで選ぶため、建物数にはマイナスを付ける（例：-10は-3より小さい）。
    candidates: list[tuple[int, float, int]] = []
    for cluster_index, building_ids in remaining_buildings.items():
      center = self._get_cluster_center(cluster_index)
      if center is not None:
        center_x, center_y = center
        # 平方根を取らなくても近い順は変わらないので、距離の二乗を使う。
        distance = (center_x - x) ** 2 + (center_y - y) ** 2
        candidates.append((-len(building_ids), distance, cluster_index))
    if not candidates:
      return set()

    _, _, next_cluster = min(candidates)
    self._logger.debug(
      f"search cluster changed: {self._current_cluster_index} -> {next_cluster}"
      f", remaining buildings: {len(remaining_buildings[next_cluster])}",
      time=self._agent_info.get_time(),
    )
    self._current_cluster_index = next_cluster
    return remaining_buildings[next_cluster]

  # 区域内の道路・建物などの座標を平均し、区域全体の中心を求める。
  # 探索済み建物も含めるため、探索が進んでも中心は変わらない。
  def _get_cluster_center(self, cluster_index: int) -> Optional[tuple[float, float]]:
    locations: list[tuple[int, int]] = []
    for entity in self._clustering.get_cluster_entities(cluster_index):
      if isinstance(entity, Area):
        x, y = entity.get_location()
        if x is not None and y is not None:
          locations.append((x, y))
    if not locations:
      return None
    return (
      sum(x for x, _ in locations) / len(locations),
      sum(y for _, y in locations) / len(locations),
    )
