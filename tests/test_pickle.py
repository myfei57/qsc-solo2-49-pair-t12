"""Pickling tank level, calibration and dosing."""

from __future__ import annotations

import pytest

from linecontrol.bus import EventBus
from linecontrol.domain.records import AcidSnapshot
from linecontrol.pickle.errors import PickleError, PickleErrorCode
from linecontrol.pickle.tank import Tank
from linecontrol.store.filestore import FileStore
from linecontrol.store.keys import KEY_ACID, KEY_DOSE_ORDERS
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


def test_dosing_plan_uses_the_trend_window(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(4.0)
    # A single dip does not dose: the trend must be established first.
    with pytest.raises(PickleError) as caught:
        tank.plan_dose(volume=20.0, target=10.0)
    assert caught.value.code is PickleErrorCode.TREND_NOT_READY
    for value in (4.0, 4.0, 4.0):
        tank.level_check(value)
    plan = tank.plan_dose(volume=20.0, target=10.0)
    assert plan.required is True
    assert plan.dose == pytest.approx(120.0)
    assert plan.current == pytest.approx(4.0)
    assert plan.basis.samples == (4.0, 4.0, 4.0, 4.0)
    assert plan.basis.ready is True
    tank.apply_dose(plan.dose, 20.0)
    assert tank.concentration() == pytest.approx(10.0)
    with pytest.raises(PickleError) as caught:
        tank.dose_volume(0.0, 10.0)
    assert caught.value.code is PickleErrorCode.TANK_VOLUME
    tank.apply_dose(5.0, 0.0)
    assert tank.concentration() == pytest.approx(10.0)


def test_plan_average_ignores_a_single_spike(tmp_path) -> None:
    tank = build(tmp_path)
    for value in (4.0, 4.0, 9.0, 4.0):
        tank.level_check(value)
    plan = tank.plan_dose(volume=10.0, target=10.0)
    # Mean of the window is 5.25, not the live 4.0 or the spiked 9.0.
    assert plan.current == pytest.approx(5.25)
    assert plan.dose == pytest.approx((10.0 - 5.25) * 10.0)


def test_recovering_trend_holds_back_the_order(tmp_path) -> None:
    tank = build(tmp_path)
    for value in (3.0, 3.0, 7.0, 7.0):
        tank.level_check(value)
    with pytest.raises(PickleError) as caught:
        tank.submit_dose_order(volume=20.0, target=10.0)
    assert caught.value.code is PickleErrorCode.TREND_RECOVERING
    assert tank.pending_dose_order() is None


def test_dose_order_submit_confirm_and_withdraw(tmp_path) -> None:
    tank = build(tmp_path)
    for value in (6.0, 6.0, 5.0, 5.0):
        tank.level_check(value)
    order = tank.submit_dose_order(volume=20.0, target=10.0)
    assert order.status.value == "submitted"
    assert order.dose == pytest.approx((10.0 - 5.5) * 20.0)
    assert tank.pending_dose_order().order_id == order.order_id
    assert len(tank.dose_orders()) == 1
    # A second submission while one is pending is refused.
    with pytest.raises(PickleError) as caught:
        tank.submit_dose_order(volume=20.0, target=10.0)
    assert caught.value.code is PickleErrorCode.ORDER_PENDING
    confirmed = tank.confirm_dose_order(order.order_id)
    assert confirmed.status.value == "confirmed"
    # Dose follows the frozen average (5.5) and is applied to the live 5.0.
    assert tank.concentration() == pytest.approx(9.5)
    assert tank.pending_dose_order() is None

    other = tank.submit_dose_order(volume=20.0, target=12.0)
    withdrawn = tank.withdraw_dose_order(other.order_id, "lab recheck")
    assert withdrawn.status.value == "withdrawn"
    assert withdrawn.reason == "lab recheck"
    assert withdrawn.decided_at is not None
    # The withdrawn order still names the window it was judged against.
    assert withdrawn.basis.samples
    assert len(withdrawn.basis.sampled_at) == len(withdrawn.basis.samples)
    with pytest.raises(PickleError) as caught:
        tank.withdraw_dose_order(other.order_id)
    assert caught.value.code is PickleErrorCode.ORDER_CLOSED
    with pytest.raises(PickleError) as caught:
        tank.confirm_dose_order("D9999")
    assert caught.value.code is PickleErrorCode.ORDER_NOT_FOUND


def test_dose_orders_persist_with_their_basis(tmp_path) -> None:
    tank = build(tmp_path)
    for value in (6.0, 6.0, 5.0, 5.0):
        tank.level_check(value)
    order = tank.submit_dose_order(volume=20.0, target=10.0)
    assert tank.store.exists(KEY_DOSE_ORDERS)

    rebuilt = build(tmp_path)
    rebuilt.restore_orders()
    pending = rebuilt.pending_dose_order()
    assert pending is not None
    assert pending.order_id == order.order_id
    assert pending.basis.samples == order.basis.samples
    assert pending.basis.average == pytest.approx(order.basis.average)


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
    assert [sample.value for sample in tank.data.trend] == [1.0, 1.0, 3.0, 3.0]
    assert tank.trend_average() == pytest.approx(2.0)
    assert tank.trend_ready() is True
    assert tank.trend_samples()[0].at is not None


def test_snapshot_reports_the_tank_view(tmp_path) -> None:
    tank = build(tmp_path)
    tank.level_check(4.0)
    tank.rinse()
    view = tank.snapshot()
    assert view["level"] == pytest.approx(4.0)
    assert view["rinsing"] is True
    assert view["rinsingPersist"] is True
