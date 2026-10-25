from typing import Optional

from rcrscore.entities import Area, Building, Civilian, EntityID, FireBrigade, Human, Refuge

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
from adf_core_python.core.component.module.complex.search import Search

from src.myteam.communication.rescue_report import create_civilian_status_message


# 次に調べに行く建物を選ぶクラス。移動や救助そのものは別の処理が担当する。
# クラスタを使わず、地図全体の未探索建物から直線距離が近いものを選ぶ。
# 建物内を確認し、救助対象の埋没者がいなければ探索済みとして記憶する。
class SampleSearch(Search):
  # 5は「探索完了」を表すmyteam独自の約束。ADF標準の定義ではない。
  # 本来は消防隊の行動を伝えるaction欄を、完了通知の目印として転用している。
  # この約束を知らないコードには、5が探索完了という意味だとは伝わらない。
  ACTION_SEARCH_COMPLETED = 5

  # 起動時に一度だけ呼ばれる。探索済み建物と、通信待ちの報告を記憶する。
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

    # 地図全体で、まだ調べる必要がある建物。
    self._unreached_building_ids: set[EntityID] = set()
    # 自分の確認と通信を合わせた探索済み建物。探索が進んでも記憶を消さない。
    self._searched_building_ids: set[EntityID] = set()
    # 上の集合のうち、ほかの消防隊の通信で知った建物だけを別にも記録する。
    self._received_searched_building_ids: set[EntityID] = set()
    # 通信開始前などに作った市民の状態報告・探索完了通知を順番に保管する。
    self._pending_search_reports: list[StandardMessage] = []
    # 同じ搬送待ち市民を毎ステップ報告しないための記録。
    self._reported_transport_civilian_ids: set[EntityID] = set()
    # 次の探索先の建物ID。行き先がなければNone。
    self._result: Optional[EntityID] = None

  # 毎ステップ、移動先を選ぶ前に記憶を更新する。救助中でも呼ばれる。
  def update_info(self, message_manager: MessageManager) -> Search:
    super().update_info(message_manager)
    # 同じステップに複数回呼ばれても、通知の処理は1回だけにする。
    if self.get_count_update_info() > 1:
      return self

    self._receive_completed_buildings(message_manager)  # 1. 他の隊の報告を記憶する。
    self._report_searched_building()                  # 2. 市民を報告し、建物を確認する。
    self._send_pending_reports(message_manager)       # 3. 保留中の報告を送る。
    # 4. 地図全体の建物から、自分や通信で確認済みの建物を除く。
    self._unreached_building_ids = self._get_search_targets()

    return self

  # 残っている候補のうち、現在位置から直線距離が最も近い建物を選ぶ。
  def calculate(self) -> Search:
    self._result = None
    position_id = self._agent_info.get_position_entity_id()
    if position_id is None:
      return self
    position = self._world_info.get_entity(position_id)
    if not isinstance(position, Area):
      return self

    # 消防隊自身の座標を使う。不明な場合は、現在いる道路・建物の座標を使う。
    myself = self._agent_info.get_myself()
    x, y = myself.get_location() if myself is not None else (None, None)
    if x is None or y is None:
      x, y = position.get_location()
    if x is None or y is None:
      # 現在位置の座標が分からなければ、距離を比較できない。
      return self

    nearest_building_id: Optional[EntityID] = None
    nearest_distance = float("inf")
    # ID順に調べるので、距離が同じなら小さいIDの建物に決まる。
    for building_id in sorted(self._unreached_building_ids, key=lambda id: id.get_value()):
      # 他の人がいる現在の建物を、その場での探索移動の目的地にしない。
      if building_id == position_id:
        continue
      building = self._world_info.get_entity(building_id)
      if not isinstance(building, Building):
        continue
      building_x, building_y = building.get_location()
      if building_x is None or building_y is None:
        continue
      # 直線距離の二乗を比較する。平方根を取らなくても近い順は変わらない。
      distance = (building_x - x) ** 2 + (building_y - y) ** 2
      if distance < nearest_distance:
        nearest_building_id = building_id
        nearest_distance = distance
    # 未探索建物がない場合や、候補の座標が分からない場合はNoneになる。
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
        # 地図上のどの建物の報告でも保存し、次の探索候補から除外する。
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
    # 対象外の隊員だけが残る場合も探索完了にして、再訪を防ぐ。
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

  # 地図全体の建物から探索済みを除く。避難所は探索対象にしない。
  def _get_search_targets(self) -> set[EntityID]:
    building_ids = {
      entity.get_entity_id()
      for entity in self._world_info.get_entities_of_types([Building])
      if not isinstance(entity, Refuge)
    }
    return building_ids - self._searched_building_ids
