"""Pickling tank level, calibration and dosing."""

from __future__ import annotations

import pytest

from linecontrol.bus import EventBus
from linecontrol.domain.records import AcidSnapshot
from linecontrol.pickle.errors import PickleError, PickleErrorCode
from linecontrol.pickle.tank import Tank
from linecontrol.store.filestore import FileStore
from linecontrol.store.keys import KEY_ACID, KEY_DOSE_HISTORY
from linecontrol.store.snapshot import load_json


def build(tmp_path) -> Tank:
    return Tank(FileStore(tmp_path), EventBus())


def test_level_gate_tracks_the_minimum(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(2.0)
    assert tank.level_ok() is False
    tank.level_check(3.1)
    assert tank.level_ok() is True
    assert tank.minimum_level() == pytest.approx(2.5)


def test_calibration_shifts_the_concentration(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(10.0)
    tank.calibrate(1.5)
    assert tank.offset() == pytest.approx(1.5)
    assert tank.concentration() == pytest.approx(11.5)
    assert tank.store.exists(KEY_ACID)


def test_calibration_rejects_an_out_of_range_offset(tmp_path) -> None:
    tank = build(tmp_path)
    with pytest.raises(PickleError) as caught:
        tank.calibrate(120.0)
    assert caught.value.code is PickleErrorCode.OFFSET_INVALID


def test_dosing_plan_uses_the_window_average(tmp_path) -> None:
    tank = build(tmp_path)
    for value in (4.0, 4.0, 6.0, 6.0):
        tank.level_check(value)
    assert tank.concentration_average() == pytest.approx(5.0)
    assert tank.concentration_delta() == pytest.approx(2.0)
    plan = tank.plan_dose(volume=20.0, target=10.0)
    assert plan.required is True
    assert plan.dose == pytest.approx(100.0)
    assert plan.basis.average == pytest.approx(5.0)
    assert plan.basis.sample_count() == 4
    with pytest.raises(PickleError) as caught:
        tank.dose_volume(0.0, 10.0)
    assert caught.value.code is PickleErrorCode.TANK_VOLUME


def test_a_single_jump_does_not_drive_the_dose(tmp_path) -> None:
    tank = build(tmp_path)
    for value in (6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 6.0, 2.0):
        tank.level_check(value)
    # The instantaneous reading collapsed to 2.0, but the window still holds
    # six 6.0 readings, so the plan follows the trend rather than the spike.
    assert tank.concentration() == pytest.approx(2.0)
    plan = tank.plan_dose(volume=20.0, target=10.0)
    assert plan.dose == pytest.approx((10.0 - 5.5) * 20.0)


def test_dose_plan_submit_confirm_and_apply(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(4.0)
    plan = tank.submit_dose_plan(volume=20.0, target=10.0)
    assert plan.status == "pending"
    assert tank.pending_dose_plan() is plan
    held = tank.dose_plan(plan.plan_id)
    assert held is not None and held.basis.average == pytest.approx(4.0)
    confirmed = tank.confirm_dose_plan()
    assert confirmed.status == "confirmed"
    assert confirmed.decided is not None
    assert tank.concentration() == pytest.approx(10.0)
    assert tank.pending_dose_plan() is None
    assert tank.dose_plan_history()[0].plan_id == plan.plan_id
    assert tank.store.exists(KEY_DOSE_HISTORY)


def test_dose_plan_can_be_withdrawn_with_its_basis(tmp_path) -> None:
    tank = build(tmp_path)
    for value in (4.0, 4.0, 6.0, 6.0):
        tank.level_check(value)
    plan = tank.submit_dose_plan(volume=20.0, target=10.0)
    concentration_before = tank.concentration()
    withdrawn = tank.withdraw_dose_plan("趋势在回升，先观察")
    assert withdrawn.status == "withdrawn"
    assert withdrawn.reason == "趋势在回升，先观察"
    assert withdrawn.basis.sample_count() == 4
    assert withdrawn.basis.average == pytest.approx(5.0)
    # Withdrawal changes neither concentration nor later samples.
    assert tank.concentration() == pytest.approx(concentration_before)
    assert tank.pending_dose_plan() is None
    # New readings after withdrawal do not rewrite the withdrawn evidence.
    tank.level_check(9.0)
    record = tank.dose_plan(plan.plan_id)
    assert record is not None and record.status == "withdrawn"
    assert record.basis.samples[-1].value == pytest.approx(6.0)
    with pytest.raises(PickleError) as caught:
        tank.withdraw_dose_plan()
    assert caught.value.code is PickleErrorCode.DOSE_NOT_FOUND


def test_only_one_dose_plan_waits_for_review(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(4.0)
    tank.submit_dose_plan(volume=20.0, target=10.0)
    with pytest.raises(PickleError) as caught:
        tank.submit_dose_plan(volume=20.0, target=10.0)
    assert caught.value.code is PickleErrorCode.DOSE_PENDING


def test_submit_rejects_a_plan_that_is_not_required(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(12.0)
    with pytest.raises(PickleError) as caught:
        tank.submit_dose_plan(volume=20.0, target=10.0)
    assert caught.value.code is PickleErrorCode.DOSE_NOT_REQUIRED


def test_pending_dose_plan_survives_a_restart(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(4.0)
    tank.calibrate(0.0)
    tank.level_check(4.0)
    plan = tank.submit_dose_plan(volume=20.0, target=10.0)
    fresh = Tank(tank.store, EventBus())
    snapshot, ok = load_json(tank.store, KEY_ACID, AcidSnapshot)
    assert ok is True
    fresh.restore_acid(snapshot)
    fresh.restore_dose_plans()
    restored = fresh.pending_dose_plan()
    assert restored is not None
    assert restored.plan_id == plan.plan_id
    assert restored.basis.average == pytest.approx(4.0)
    confirmed = fresh.confirm_dose_plan()
    assert confirmed.status == "confirmed"
    assert fresh.concentration() == pytest.approx(10.0)



def test_rinse_valve_and_flush(tmp_path) -> None:
    tank = build(tmp_path)
    tank.rinse()
    assert tank.rinsing() is True
    assert tank.flushed() is False
    snapshot, ok = tank.rinse_persisted()
    assert ok is True and snapshot.active is True
    tank.rinse_flush()
    assert tank.flushed() is True
    tank.rinse_stop()
    assert tank.rinsing() is False
    other = build(tmp_path / "restore")
    other.restore_rinse(True)
    assert other.rinsing() is True


def test_acid_snapshot_restore(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(6.0)
    tank.calibrate(-0.5)
    snapshot, ok = load_json(tank.store, KEY_ACID, AcidSnapshot)
    assert ok is True
    fresh = build(tmp_path / "fresh")
    fresh.restore_acid(snapshot)
    assert fresh.level() == pytest.approx(6.0)
    assert fresh.offset() == pytest.approx(-0.5)


def test_level_trend_reports_the_direction(tmp_path) -> None:
    tank = build(tmp_path)
    for value in (1.0, 1.0, 3.0, 3.0):
        tank.level_check(value)
    assert tank.level_trend() == pytest.approx(2.0)
    assert tank.data.trend == [1.0, 1.0, 3.0, 3.0]


def test_snapshot_reports_the_tank_view(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(4.0)
    tank.rinse()
    view = tank.snapshot()
    assert view["level"] == pytest.approx(4.0)
    assert view["rinsing"] is True
    assert view["rinsingPersist"] is True
