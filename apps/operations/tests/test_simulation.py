"""Train movement simulation."""
import datetime as dt

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.bookings.exceptions import SimulationError
from apps.bookings.services.availability import get_min_boardable_index
from apps.core.testing import make_route_train, make_user, next_run_date
from apps.operations.models import ActivityLog, TrainSimulation
from apps.operations.services.simulation import (
    advance_simulation,
    apply_auto_advance,
    get_or_create_simulation,
    set_auto_advance,
    set_paused,
    simulation_snapshot,
    start_simulation,
)

S = TrainSimulation.Status


class SimulationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.train = make_route_train()
        cls.admin = make_user("admin1", role=User.Role.ADMIN)

    def setUp(self):
        self.date = next_run_date(self.train, 0)
        self.sim = get_or_create_simulation(self.train, self.date)

    def test_state_machine_walks_the_whole_route(self):
        self.assertEqual(get_min_boardable_index(self.train, self.date), 0)
        sim = start_simulation(self.sim, self.admin)
        self.assertEqual((sim.status, sim.current_index), (S.AT_STATION, 0))
        self.assertEqual(sim.min_boardable_index(5), 0)
        expected = [
            (S.IN_TRANSIT, 0, 1), (S.AT_STATION, 1, 1), (S.IN_TRANSIT, 1, 2), (S.AT_STATION, 2, 2),
            (S.IN_TRANSIT, 2, 3), (S.AT_STATION, 3, 3), (S.IN_TRANSIT, 3, 4), (S.AT_STATION, 4, 4),
            (S.COMPLETED, 4, 5),
        ]
        for status, index, min_boardable in expected:
            sim = advance_simulation(sim, self.admin)
            self.assertEqual((sim.status, sim.current_index), (status, index))
            self.assertEqual(sim.min_boardable_index(5), min_boardable)
        with self.assertRaises(SimulationError):
            advance_simulation(sim, self.admin)
        self.assertTrue(ActivityLog.objects.filter(action="SIM_COMPLETED").exists())

    def test_move_to_next_station_shortcut(self):
        sim = start_simulation(self.sim, self.admin)
        sim = advance_simulation(sim, self.admin, to_next_station=True)
        self.assertEqual((sim.status, sim.current_index), (S.AT_STATION, 1))

    def test_cannot_move_before_start_or_while_paused(self):
        with self.assertRaises(SimulationError):
            advance_simulation(self.sim, self.admin)
        sim = start_simulation(self.sim, self.admin)
        with self.assertRaises(SimulationError):
            start_simulation(sim, self.admin)
        sim = set_paused(sim, self.admin, True)
        with self.assertRaises(SimulationError):
            advance_simulation(sim, self.admin)
        sim = set_paused(sim, self.admin, False)
        advance_simulation(sim, self.admin)

    def test_past_runs_cannot_start(self):
        past = timezone.localdate() - dt.timedelta(days=3)
        sim = get_or_create_simulation(self.train, past)
        with self.assertRaises(SimulationError):
            start_simulation(sim, self.admin)

    def test_auto_advance_applies_elapsed_steps(self):
        sim = start_simulation(self.sim, self.admin)
        sim = set_auto_advance(sim, self.admin, True, interval=10)
        TrainSimulation.objects.filter(pk=sim.pk).update(last_moved_at=timezone.now() - dt.timedelta(seconds=25))
        sim.refresh_from_db()
        sim = apply_auto_advance(sim)
        self.assertEqual((sim.status, sim.current_index), (S.AT_STATION, 1))

    def test_snapshot(self):
        snap = simulation_snapshot(None, self.train, self.date)
        self.assertEqual(snap["status"], S.SCHEDULED)
        self.assertEqual(snap["progress"], 0)
        sim = start_simulation(self.sim, self.admin)
        sim = advance_simulation(sim, self.admin)
        snap = simulation_snapshot(sim, self.train, self.date)
        self.assertEqual(snap["stops"][0]["state"], "passed")
        self.assertEqual(snap["next_code"], "TB")
        self.assertGreater(snap["progress"], 0)
