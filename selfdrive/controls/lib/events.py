from enum import IntEnum
from typing import Dict, Union, Callable, Any

from cereal import log, car
import cereal.messaging as messaging
from common.realtime import DT_CTRL
from selfdrive.config import Conversions as CV
from selfdrive.locationd.calibrationd import MIN_SPEED_FILTER

AlertSize = log.ControlsState.AlertSize
AlertStatus = log.ControlsState.AlertStatus
VisualAlert = car.CarControl.HUDControl.VisualAlert
AudibleAlert = car.CarControl.HUDControl.AudibleAlert
EventName = car.CarEvent.EventName

# Alert priorities
class Priority(IntEnum):
  LOWEST = 0
  LOWER = 1
  LOW = 2
  MID = 3
  HIGH = 4
  HIGHEST = 5

# Event types
class ET:
  ENABLE = 'enable'
  PRE_ENABLE = 'preEnable'
  NO_ENTRY = 'noEntry'
  WARNING = 'warning'
  USER_DISABLE = 'userDisable'
  SOFT_DISABLE = 'softDisable'
  IMMEDIATE_DISABLE = 'immediateDisable'
  PERMANENT = 'permanent'

# get event name from enum
EVENT_NAME = {v: k for k, v in EventName.schema.enumerants.items()}


class Events:
  def __init__(self):
    self.events = []
    self.static_events = []
    self.events_prev = dict.fromkeys(EVENTS.keys(), 0)

  @property
  def names(self):
    return self.events

  def __len__(self):
    return len(self.events)

  def add(self, event_name, static=False):
    if static:
      self.static_events.append(event_name)
    self.events.append(event_name)

  def clear(self):
    self.events_prev = {k: (v+1 if k in self.events else 0) for k, v in self.events_prev.items()}
    self.events = self.static_events.copy()

  def any(self, event_type):
    for e in self.events:
      if event_type in EVENTS.get(e, {}).keys():
        return True
    return False

  def create_alerts(self, event_types, callback_args=None):
    if callback_args is None:
      callback_args = []

    ret = []
    for e in self.events:
      types = EVENTS[e].keys()
      for et in event_types:
        if et in types:
          alert = EVENTS[e][et]
          if not isinstance(alert, Alert):
            alert = alert(*callback_args)

          if DT_CTRL * (self.events_prev[e] + 1) >= alert.creation_delay:
            alert.alert_type = f"{EVENT_NAME[e]}/{et}"
            alert.event_type = et
            ret.append(alert)
    return ret

  def add_from_msg(self, events):
    for e in events:
      self.events.append(e.name.raw)

  def to_msg(self):
    ret = []
    for event_name in self.events:
      event = car.CarEvent.new_message()
      event.name = event_name
      for event_type in EVENTS.get(event_name, {}).keys():
        setattr(event, event_type , True)
      ret.append(event)
    return ret

class Alert:
  def __init__(self,
               alert_text_1: str,
               alert_text_2: str,
               alert_status: log.ControlsState.AlertStatus,
               alert_size: log.ControlsState.AlertSize,
               alert_priority: Priority,
               visual_alert: car.CarControl.HUDControl.VisualAlert,
               audible_alert: car.CarControl.HUDControl.AudibleAlert,
               duration_sound: float,
               duration_hud_alert: float,
               duration_text: float,
               alert_rate: float = 0.,
               creation_delay: float = 0.):

    self.alert_text_1 = alert_text_1
    self.alert_text_2 = alert_text_2
    self.alert_status = alert_status
    self.alert_size = alert_size
    self.alert_priority = alert_priority
    self.visual_alert = visual_alert
    self.audible_alert = audible_alert

    self.duration_sound = duration_sound
    self.duration_hud_alert = duration_hud_alert
    self.duration_text = duration_text

    self.alert_rate = alert_rate
    self.creation_delay = creation_delay

    self.start_time = 0.
    self.alert_type = ""
    self.event_type = None

  def __str__(self) -> str:
    return f"{self.alert_text_1}/{self.alert_text_2} {self.alert_priority} {self.visual_alert} {self.audible_alert}"

  def __gt__(self, alert2) -> bool:
    return self.alert_priority > alert2.alert_priority

class NoEntryAlert(Alert):
  def __init__(self, alert_text_2, audible_alert=AudibleAlert.chimeError,
               visual_alert=VisualAlert.none, duration_hud_alert=2.):
    super().__init__("�������Ϸ� ���Ұ�", alert_text_2, AlertStatus.normal,
                     AlertSize.mid, Priority.LOW, visual_alert,
                     audible_alert, .4, duration_hud_alert, 3.)


class SoftDisableAlert(Alert):
  def __init__(self, alert_text_2):
    super().__init__("�ڵ��� ��� ����ּ���", alert_text_2,
                     AlertStatus.userPrompt, AlertSize.full,
                     Priority.MID, VisualAlert.steerRequired,
                     AudibleAlert.chimeError, .1, 2., 2.),


class ImmediateDisableAlert(Alert):
  def __init__(self, alert_text_2, alert_text_1="�ڵ��� ��� ����ּ���"):
    super().__init__(alert_text_1, alert_text_2,
                     AlertStatus.critical, AlertSize.full,
                     Priority.HIGHEST, VisualAlert.steerRequired,
                     AudibleAlert.chimeWarningRepeat, 2.2, 3., 4.),

class EngagementAlert(Alert):
  def __init__(self, audible_alert=True):
    super().__init__("", "",
                     AlertStatus.normal, AlertSize.none,
                     Priority.MID, VisualAlert.none,
                     audible_alert, .2, 0., 0.),

class NormalPermanentAlert(Alert):
  def __init__(self, alert_text_1, alert_text_2):
    super().__init__(alert_text_1, alert_text_2,
                     AlertStatus.normal, AlertSize.mid,
                     Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),

# ********** alert callback functions **********

def below_steer_speed_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  speed = int(round(CP.minSteerSpeed * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH)))
  unit = "km/h" if metric else "mph"
  return Alert(
    "�ڵ��� ����ּ���",
    "%d %s �̻��� �ӵ����� �ڵ�����˴ϴ�" % (speed, unit),
    AlertStatus.userPrompt, AlertSize.mid,
    Priority.MID, VisualAlert.steerRequired, AudibleAlert.none, 0., 0.4, .3)

def calibration_incomplete_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  speed = int(MIN_SPEED_FILTER * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH))
  unit = "km/h" if metric else "mph"
  return Alert(
    "Ķ���극�̼� �������Դϴ� : %d%%" % sm['liveCalibration'].calPerc,
    "�ӵ��� %d %s �̻����� �������ּ���" % (speed, unit),
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0., 0., .2)

def no_gps_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  gps_integrated = sm['health'].hwType in [log.HealthData.HwType.uno, log.HealthData.HwType.dos]
  return Alert(
    "GPS ���źҷ�",
    "GPS ������� �� ���׳��� �����ϼ���" if gps_integrated else "GPS ���׳��� �����ϼ���",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=300.)

def wrong_car_mode_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  text = "ũ���� ��Ȱ������"
  if CP.carName == "honda":
    text = "���� ����ġ OFF"
  return NoEntryAlert(text, duration_hud_alert=0.)

def auto_lane_change_alert(CP: car.CarParams, sm: messaging.SubMaster, metric: bool) -> Alert:
  alc_timer = sm['pathPlan'].autoLaneChangeTimer
  return Alert(
    "�ڵ����������� %d�� �ڿ� ���۵˴ϴ�" % alc_timer,
    "������ ������ Ȯ���ϼ���",
    AlertStatus.normal, AlertSize.mid,
    Priority.LOWER, VisualAlert.steerRequired, AudibleAlert.none, 0., .1, .1, alert_rate=0.75)


EVENTS: Dict[int, Dict[str, Union[Alert, Callable[[Any, messaging.SubMaster, bool], Alert]]]] = {
  # ********** events with no alerts **********

  # ********** events only containing alerts displayed in all states **********

  EventName.debugAlert: {
    ET.PERMANENT: Alert(
      "����� ���",
      "",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .1, .1, .1),
  },

  EventName.startup: {
    ET.PERMANENT: Alert(
      "�������Ϸ� ����غ� �Ϸ�",
      "�׻� �ڵ��� ��� ���θ� �ֽ��ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 15.),
  },

  EventName.startupMaster: {
    ET.PERMANENT: Alert(
      "�������Ϸ� ����غ� �Ϸ�",
      "�׻� �ڵ��� ��� ���θ� �ֽ��ϼ���",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 15.),
  },

  EventName.startupNoControl: {
    ET.PERMANENT: Alert(
      "���ķ ���",
      "�׻� �ڵ��� ��� ���θ� �ֽ��ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 15.),
  },

  EventName.startupNoCar: {
    ET.PERMANENT: Alert(
      "���ķ ��� : ȣȯ�����ʴ� ����",
      "�׻� �ڵ��� ��� ���θ� �ֽ��ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 15.),
  },

  EventName.startupOneplus: {
    ET.PERMANENT: Alert(
      "WARNING: Original EON deprecated",
      "Device will no longer update",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., 15.),
  },

  EventName.invalidLkasSetting: {
    ET.PERMANENT: Alert(
      "���� LKAS ��ư ����Ȯ��",
      "���� LKAS ��ư OFF�� Ȱ��ȭ�˴ϴ�",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.communityFeatureDisallowed: {
    # LOW priority to overcome Cruise Error
    ET.PERMANENT: Alert(
      "Ŀ�´�Ƽ ��� ������",
      "�����ڼ������� Ŀ�´�Ƽ ����� Ȱ��ȭ���ּ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.carUnrecognized: {
    ET.PERMANENT: Alert(
      "���ķ ���",
      "�����ν� �Ұ� - �ΰ�����Ʈ�� Ȯ���ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.stockAeb: {
    ET.PERMANENT: Alert(
      "�극��ũ!",
      "�ߵ� ����",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 1., 2., 2.),
  },

  EventName.stockFcw: {
    ET.PERMANENT: Alert(
      "�극��ũ!",
      "�ߵ� ����",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.none, 1., 2., 2.),
  },

  EventName.fcw: {
    ET.PERMANENT: Alert(
      "�극��ũ!",
      "�ߵ� ����",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGHEST, VisualAlert.fcw, AudibleAlert.chimeWarningRepeat, 1., 2., 2.),
  },

  EventName.ldw: {
    ET.PERMANENT: Alert(
      "�ڵ��� ����ּ���",
      "������Ż ������",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimePrompt, 1., 2., 3.),
  },

  # ********** events only containing alerts that display while engaged **********

  EventName.gasPressed: {
    ET.PRE_ENABLE: Alert(
      "�����дް����� �������Ϸ��� �극��ũ�� ��������ʽ��ϴ�",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, .0, .0, .1, creation_delay=1.),
  },

  EventName.vehicleModelInvalid: {
    ET.WARNING: Alert(
      "���� �Ű����� �ĺ� ����",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWEST, VisualAlert.steerRequired, AudibleAlert.none, .0, .0, .1),
  },

  EventName.steerTempUnavailableMute: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ���",
      "�������� �Ͻ������� ���Ұ�",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .2, .2, .2),
  },

  EventName.preDriverDistracted: {
    ET.WARNING: Alert(
      "���θ� �ֽ��ϼ��� : ������ �����ֽ� �Ҿ�",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1),
  },

  EventName.promptDriverDistracted: {
    ET.WARNING: Alert(
      "���θ� �ֽ��ϼ���",
      "������ �����ֽ� �Ҿ�",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.chimeWarning2Repeat, .1, .1, .1),
  },

  EventName.driverDistracted: {
    ET.WARNING: Alert(
      "������� ������ �����˴ϴ�",
      "������ �����ֽ� �Ҿ�",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.chimeWarningRepeat, .1, .1, .1),
  },

  EventName.preDriverUnresponsive: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ��� : ������ �ν� �Ұ�",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.promptDriverUnresponsive: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ���",
      "������ ������������",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.MID, VisualAlert.steerRequired, AudibleAlert.chimeWarning2Repeat, .1, .1, .1),
  },

  EventName.driverUnresponsive: {
    ET.WARNING: Alert(
      "������� ������ �����˴ϴ�",
      "������ ������������",
      AlertStatus.critical, AlertSize.full,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.chimeWarningRepeat, .1, .1, .1),
  },

  EventName.driverMonitorLowAcc: {
    ET.WARNING: Alert(
      "������ ����͸� Ȯ��",
      "������ ����͸� ���°� �������Դϴ�",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .4, 0., 1.5),
  },

  EventName.manualRestart: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ���",
      "�������� ��Ȱ��ȭ�ϼ���",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.resumeRequired: {
    ET.WARNING: Alert(
      "������ ����",
      "�̵��Ϸ��� RES��ư�� ��������",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
  },

  EventName.belowSteerSpeed: {
    ET.WARNING: below_steer_speed_alert,
  },

  EventName.preLaneChangeLeft: {
    ET.WARNING: Alert(
      "������ �����մϴ�",
      "���������� ������ Ȯ���ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.preLaneChangeRight: {
    ET.WARNING: Alert(
      "������ �����մϴ�",
      "���������� ������ Ȯ���ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1, alert_rate=0.75),
  },

  EventName.laneChangeBlocked: {
    ET.WARNING: Alert(
      "������ ��������",
      "������ ������ �����Ǵ� ����ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1),
  },

  EventName.laneChange: {
    ET.WARNING: Alert(
      "������ �����մϴ�",
      "������ ������ �����ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.none, .0, .1, .1),
  },

  EventName.steerSaturated: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ���",
      "�������� ������ �ʰ���",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimePrompt, 1., 1., 1.),
  },
  
  EventName.fanMalfunction: {
    ET.PERMANENT: NormalPermanentAlert("FAN ���۵�", "�ϵ��� �����ϼ���"),
  },

  EventName.cameraMalfunction: {
    ET.PERMANENT: NormalPermanentAlert("ī�޶� ���۵�", "��ġ�� �����ϼ���"),
  },

  # ********** events that affect controls state transitions **********

  EventName.pcmEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.chimeEngage),
  },

  EventName.buttonEnable: {
    ET.ENABLE: EngagementAlert(AudibleAlert.chimeEngage),
  },

  EventName.pcmDisable: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
  },

  EventName.buttonCancel: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
  },

  EventName.brakeHold: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("�극��ũ ������"),
  },

  EventName.parkBrake: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("���� �극��ũ�� �����ϼ���"),
  },

  EventName.pedalPressed: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("�극��ũ ������",
                              visual_alert=VisualAlert.brakePressed),
  },

  EventName.wrongCarMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: wrong_car_mode_alert,
  },

  EventName.wrongCruiseMode: {
    ET.USER_DISABLE: EngagementAlert(AudibleAlert.chimeDisengage),
    ET.NO_ENTRY: NoEntryAlert("�Ƽ��ũ��� Ȱ��ȭ�ϼ���"),
  },

  EventName.steerTempUnavailable: {
    ET.WARNING: Alert(
      "�ڵ��� ����ּ���",
      "�������� �Ͻ������� ���Ұ�",
      AlertStatus.userPrompt, AlertSize.mid,
      Priority.LOW, VisualAlert.steerRequired, AudibleAlert.chimeWarning1, .4, 2., 3.),
    ET.NO_ENTRY: NoEntryAlert("�������� �Ͻ������� ���Ұ�",
                              duration_hud_alert=0.),
  },

  EventName.outOfSpace: {
    ET.PERMANENT: Alert(
      "������� ����",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("������� ����",
                              duration_hud_alert=0.),
  },

  EventName.belowEngageSpeed: {
    ET.NO_ENTRY: NoEntryAlert("�ӵ��� �����ּ���"),
  },

  EventName.sensorDataInvalid: {
    ET.PERMANENT: Alert(
      "��ġ ���� ����",
      "��ġ ������ �簡������",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("��ġ ���� ����"),
  },

  EventName.noGps: {
    ET.PERMANENT: no_gps_alert,
  },

  EventName.soundsUnavailable: {
    ET.PERMANENT: NormalPermanentAlert("����Ŀ�� ���������ʽ��ϴ�", "�̿��� ����� ���ּ���"),
    ET.NO_ENTRY: NoEntryAlert("����Ŀ�� ���������ʽ��ϴ�"),
  },

  EventName.tooDistracted: {
    ET.NO_ENTRY: NoEntryAlert("���� ������ �ʹ�����"),
  },

  EventName.overheat: {
    ET.PERMANENT: Alert(
      "��ġ ������",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.SOFT_DISABLE: SoftDisableAlert("��ġ ������"),
    ET.NO_ENTRY: NoEntryAlert("��ġ ������"),
  },

  EventName.wrongGear: {
    ET.SOFT_DISABLE: SoftDisableAlert("�� [D]�� �����ϼ���"),
    ET.NO_ENTRY: NoEntryAlert("�� [D]�� �����ϼ���"),
  },

  EventName.calibrationInvalid: {
    ET.PERMANENT: NormalPermanentAlert("Ķ���극�̼� ����", "��ġ ��ġ������ Ķ���극�̼��� �ٽ��ϼ���"),
    ET.SOFT_DISABLE: SoftDisableAlert("Ķ���극�̼� ���� : ��ġ ��ġ������ Ķ���극�̼��� �ٽ��ϼ���"),
    ET.NO_ENTRY: NoEntryAlert("Ķ���극�̼� ���� : ��ġ ��ġ������ Ķ���극�̼��� �ٽ��ϼ���"),
  },

  EventName.calibrationIncomplete: {
    ET.PERMANENT: calibration_incomplete_alert,
    ET.SOFT_DISABLE: SoftDisableAlert("Ķ���극�̼� �������Դϴ�"),
    ET.NO_ENTRY: NoEntryAlert("Ķ���극�̼� �������Դϴ�"),
  },

  EventName.doorOpen: {
    ET.SOFT_DISABLE: SoftDisableAlert("���� ����"),
    ET.NO_ENTRY: NoEntryAlert("���� ����"),
  },

  EventName.seatbeltNotLatched: {
    ET.SOFT_DISABLE: SoftDisableAlert("������Ʈ�� �������ּ���"),
    ET.NO_ENTRY: NoEntryAlert("������Ʈ�� �������ּ���"),
  },

  EventName.espDisabled: {
    ET.SOFT_DISABLE: SoftDisableAlert("ESP ����"),
    ET.NO_ENTRY: NoEntryAlert("ESP ����"),
  },

  EventName.lowBattery: {
    ET.SOFT_DISABLE: SoftDisableAlert("���͸� ����"),
    ET.NO_ENTRY: NoEntryAlert("���͸� ����"),
  },

  EventName.commIssue: {
    ET.SOFT_DISABLE: SoftDisableAlert("��ġ ���μ��� ��ſ���"),
    ET.NO_ENTRY: NoEntryAlert("��ġ ���μ��� ��ſ���",
                              audible_alert=AudibleAlert.chimeDisengage),
  },

  EventName.radarCommIssue: {
    ET.SOFT_DISABLE: SoftDisableAlert("���� ���̴� ��ſ���"),
    ET.NO_ENTRY: NoEntryAlert("���� ���̴� ��ſ���",
                              audible_alert=AudibleAlert.chimeDisengage),
  },

  EventName.radarCanError: {
    ET.SOFT_DISABLE: SoftDisableAlert("���̴� ���� : ������ �簡���ϼ���"),
    ET.NO_ENTRY: NoEntryAlert("���̴� ���� : ������ �簡���ϼ���"),
  },

  EventName.radarFault: {
    ET.SOFT_DISABLE: SoftDisableAlert("���̴� ���� : ������ �簡���ϼ���"),
    ET.NO_ENTRY : NoEntryAlert("���̴� ���� : ������ �簡���ϼ���"),
  },

  EventName.modeldLagging: {
    ET.SOFT_DISABLE: SoftDisableAlert("����� ������"),
    ET.NO_ENTRY : NoEntryAlert("����� ������"),
  },

  EventName.posenetInvalid: {
    ET.SOFT_DISABLE: SoftDisableAlert("�����νĻ��°� ���������� ���ǿ����ϼ���"),
    ET.NO_ENTRY: NoEntryAlert("�����νĻ��°� ���������� ���ǿ����ϼ���"),
  },

  EventName.deviceFalling: {
    ET.SOFT_DISABLE: SoftDisableAlert("��ġ�� ����Ʈ���� ������"),
    ET.NO_ENTRY: NoEntryAlert("��ġ�� ����Ʈ���� ������"),
  },

  EventName.lowMemory: {
    ET.SOFT_DISABLE: SoftDisableAlert("�޸� ���� : ��ġ�� �簡���ϼ���"),
    ET.PERMANENT: NormalPermanentAlert("�޸� ����", "��ġ�� �簡���ϼ���"),
    ET.NO_ENTRY : NoEntryAlert("�޸� ���� : ��ġ�� �簡���ϼ���",
                               audible_alert=AudibleAlert.chimeDisengage),
  },

  EventName.controlsFailed: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("��Ʈ�� ����"),
    ET.NO_ENTRY: NoEntryAlert("��Ʈ�� ����"),
  },

  EventName.controlsMismatch: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("��Ʈ�� ����ġ"),
  },

  EventName.canError: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("CAN ���� : �ϵ��� �����ϼ���"),
    ET.PERMANENT: Alert(
      "CAN ���� : �ϵ��� �����ϼ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=1.),
    ET.NO_ENTRY: NoEntryAlert("CAN ���� : �ϵ��� �����ϼ���"),
  },

  EventName.steerUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("LKAS ���� : ������ �簡���ϼ���"),
    ET.PERMANENT: Alert(
      "LKAS ���� : ������ �簡���ϼ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("LKAS Fault: Restart the Car"),
  },

  EventName.brakeUnavailable: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("Cruise Fault: Restart the Car"),
    ET.PERMANENT: Alert(
      "ũ���� ���� : ������ �簡���ϼ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("ũ���� ���� : ������ �簡���ϼ���"),
  },

  EventName.reverseGear: {
    ET.PERMANENT: Alert(
      "��� [R] ����",
      "",
      AlertStatus.normal, AlertSize.full,
      Priority.LOWEST, VisualAlert.none, AudibleAlert.none, 0., 0., .2, creation_delay=0.5),
    ET.SOFT_DISABLE: SoftDisableAlert("��� [R] ����"),
    ET.NO_ENTRY: NoEntryAlert("��� [R] ����"),
  },

  EventName.cruiseDisabled: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("ũ���� ����"),
  },

  EventName.plannerError: {
    ET.SOFT_DISABLE: SoftDisableAlert("�÷��� �ַ�� ����"),
    ET.NO_ENTRY: NoEntryAlert("�÷��� �ַ�� ����"),
  },

  EventName.relayMalfunction: {
    ET.IMMEDIATE_DISABLE: ImmediateDisableAlert("�ϳ׽� ���۵�"),
    ET.PERMANENT: NormalPermanentAlert("�ϳ׽� ���۵�", "�ϵ��� �����ϼ���"),
    ET.NO_ENTRY: NoEntryAlert("�ϳ׽� ���۵�"),
  },

  EventName.noTarget: {
    ET.IMMEDIATE_DISABLE: Alert(
      "�������Ϸ� ���Ұ�",
      "���� �������� �����ϴ�",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.chimeDisengage, .4, 2., 3.),
    ET.NO_ENTRY : NoEntryAlert("No Close Lead Car"),
  },

  EventName.speedTooLow: {
    ET.IMMEDIATE_DISABLE: Alert(
      "�������Ϸ� ���Ұ�",
      "�ӵ��� ���̰� �簡���ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.none, AudibleAlert.chimeDisengage, .4, 2., 3.),
  },

  EventName.speedTooHigh: {
    ET.WARNING: Alert(
      "�ӵ��� �ʹ� �����ϴ�",
      "�ӵ��� �ٿ��ּ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.HIGH, VisualAlert.steerRequired, AudibleAlert.none, 2.2, 3., 4.),
    ET.NO_ENTRY: Alert(
      "�ӵ��� �ʹ� �����ϴ�",
      "�ӵ��� ���̰� �簡���ϼ���",
      AlertStatus.normal, AlertSize.mid,
      Priority.LOW, VisualAlert.none, AudibleAlert.chimeError, .4, 2., 3.),
  },

  # TODO: this is unclear, update check only happens offroad
  EventName.internetConnectivityNeeded: {
    ET.PERMANENT: NormalPermanentAlert("���ͳ��� �����ϼ���", "������Ʈ üũ�� Ȱ��ȭ �˴ϴ�"),
    ET.NO_ENTRY: NoEntryAlert("���ͳ��� �����ϼ���",
                              audible_alert=AudibleAlert.chimeDisengage),
  },

  EventName.lowSpeedLockout: {
    ET.PERMANENT: Alert(
      "ũ���� ���� : ������ �簡���ϼ���",
      "",
      AlertStatus.normal, AlertSize.small,
      Priority.LOWER, VisualAlert.none, AudibleAlert.none, 0., 0., .2),
    ET.NO_ENTRY: NoEntryAlert("ũ���� ���� : ������ �簡���ϼ���"),
  },
  
  EventName.turningIndicatorOn: {
    ET.WARNING: Alert(
      "�������õ� �����߿��� �ڵ��� ����ּ���",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, .0, .0, .2),
  },

  EventName.lkasButtonOff: {
    ET.WARNING: Alert(
      "������ LKAS��ư�� Ȯ�����ּ���",
      "",
      "",
      AlertStatus.userPrompt, AlertSize.small,
      Priority.LOW, VisualAlert.none, AudibleAlert.none, 0., 0., .1),
  },

  EventName.autoLaneChange: {
    ET.WARNING: auto_lane_change_alert,
  },

  EventName.sccSmootherStatus: {
    ET.PERMANENT: Alert("","", AlertStatus.normal, AlertSize.none,
      Priority.HIGH, VisualAlert.none, AudibleAlert.chimeWarning1, .4, .1, .1),
  },

  EventName.slowingDownSpeed: {
    ET.PERMANENT: Alert("�ӵ��� �����մϴ�","", AlertStatus.normal, AlertSize.small,
      Priority.MID, VisualAlert.none, AudibleAlert.none, 0., .1, .1),
  },

  EventName.slowingDownSpeedSound: {
    ET.PERMANENT: Alert("�ӵ��� �����մϴ�","", AlertStatus.normal, AlertSize.small,
      Priority.HIGH, VisualAlert.none, AudibleAlert.chimeSlowingDownSpeed, 6., 2., 2.),
  },

}
