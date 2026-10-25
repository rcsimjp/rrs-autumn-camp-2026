from rcrscore.entities import AmbulanceTeam, Civilian, FireBrigade

from adf_core_python.core.agent.communication.standard.bundle.information.message_ambulance_team import (
  MessageAmbulanceTeam,
)
from adf_core_python.core.agent.communication.standard.bundle.information.message_civilian import (
  MessageCivilian,
)
from adf_core_python.core.agent.communication.standard.bundle.information.message_fire_brigade import (
  MessageFireBrigade,
)
from adf_core_python.core.agent.communication.standard.bundle.standard_message import (
  StandardMessage,
)
from adf_core_python.core.agent.communication.standard.bundle.standard_message_priority import (
  StandardMessagePriority,
)


# 市民の状態報告を作る。Searchによる発見時と、Detectorによる救出完了時に共用する。
def create_civilian_status_message(sender: FireBrigade, civilian: Civilian) -> MessageCivilian:
  message = MessageCivilian(
    is_wireless_message=True,
    civilian=civilian,
    priority=StandardMessagePriority.HIGH,
    sender_entity_id=sender.get_entity_id(),
  )
  # ADF 0.2.16はコンストラクタ内の「値 or None」で0を欠落させる。
  # このメッセージだけ補い、標準の通信形式に正しい観測値0を載せる。
  # 相手の標準受信処理にも同じ問題があるため、これだけでは受信後の0は保証できない。
  message._civilian_buriedness = civilian.get_buriedness()
  if civilian.get_damage() == 0:
    message._civilian_damage = 0
  return message


# 標準メッセージを作る処理だけをまとめる。救助完了かどうかはDetectorが判断する。
def create_rescue_completed_messages(
  rescuer: FireBrigade, target: Civilian | AmbulanceTeam
) -> list[StandardMessage]:
  if isinstance(target, Civilian):
    target_message: StandardMessage = create_civilian_status_message(rescuer, target)
  else:
    ambulance_message = MessageAmbulanceTeam(
      is_wireless_message=True,
      ambulance_team=target,
      # 相手の行動・目標は分からないので、通信形式で許される未設定値を使う。
      action=None,  # type: ignore[arg-type]
      target_entity_id=None,  # type: ignore[arg-type]
      priority=StandardMessagePriority.HIGH,
      sender_entity_id=rescuer.get_entity_id(),
    )
    ambulance_message._ambulance_team_buriedness = target.get_buriedness()
    if target.get_damage() == 0:
      ambulance_message._ambulance_team_damage = 0
    target_message = ambulance_message

  # 「この消防隊が、この対象を救助した」という行動報告も標準値4で送る。
  rescue_message = MessageFireBrigade(
    is_wireless_message=True,
    fire_brigade=rescuer,
    action=MessageFireBrigade.ACTION_RESCUE,
    target_entity_id=target.get_entity_id(),
    priority=StandardMessagePriority.HIGH,
    sender_entity_id=rescuer.get_entity_id(),
  )
  rescue_message._fire_brigade_buriedness = rescuer.get_buriedness()
  if rescuer.get_damage() == 0:
    rescue_message._fire_brigade_damage = 0
  return [target_message, rescue_message]
