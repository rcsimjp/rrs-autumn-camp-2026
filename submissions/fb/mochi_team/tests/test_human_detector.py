"""Run from the team directory: .venv/bin/python -m unittest discover -s tests."""
import math
import unittest
from unittest.mock import Mock

from rcrscore.entities import AmbulanceTeam, Building, Civilian, EntityID, FireBrigade, Refuge
from src.mochi_team.module.complex.sample_human_detector import SampleHumanDetector


class HumanDetectorTest(unittest.TestCase):
  def setUp(self):
    self.detector = SampleHumanDetector.__new__(SampleHumanDetector)
    self.detector._result = None
    self.detector._agent_info = Mock()
    self.detector._agent_info.get_entity_id.return_value = EntityID(1)
    self.detector._clustering = Mock()
    self.detector._clustering.get_cluster_index.return_value = 0
    self.detector._clustering.get_cluster_entities.return_value = []
    self.building = Building(100)
    self.people = []
    self.brigades = []
    self.distances = {}
    world = self.detector._world_info = Mock()
    world.get_entities_of_types.side_effect = (
      lambda types: (
        [] if types == [Refuge]
        else self.brigades if types == [FireBrigade] else self.people
      )
    )
    world.get_entity.side_effect = lambda key: (
      self.building if key == self.building.get_entity_id()
      else next((p for p in self.people if p.get_entity_id() == key), None)
    )
    world.get_distance.side_effect = lambda start, end: self.distances[end]

  def person(self, ident, buriedness=5, hp=10000, damage=0, distance=0, kind=Civilian):
    person = kind(ident)
    person.get_hp_property().set_value(hp)
    if damage is not None:
      person.get_damage_property().set_value(damage)
    person.get_buriedness_property().set_value(buriedness)
    person.get_position_property().set_value(self.building.get_entity_id())
    self.people.append(person)
    self.distances[person.get_entity_id()] = distance
    return person.get_entity_id()

  def test_shorter_rescue_can_beat_nearest(self):
    self.person(2, buriedness=50)
    fast = self.person(3, distance=60000)
    self.assertEqual(self.detector._select_target(), fast)

  def test_urgent_but_feasible_target_gets_priority(self):
    self.person(2, hp=10000, damage=100)
    urgent = self.person(3, hp=1800, damage=100)
    self.assertEqual(self.detector._select_target(), urgent)

  def test_difficult_target_remains_available(self):
    difficult = self.person(2, buriedness=50, hp=100, damage=100)
    self.assertEqual(self.detector._select_target(), difficult)
    feasible = self.person(3)
    self.assertEqual(self.detector._select_target(), feasible)

  def test_cluster_is_a_bonus_not_a_restriction(self):
    self.person(2, buriedness=50)
    self.detector._clustering.get_cluster_entities.return_value = [self.people[0]]
    outside = self.person(3)
    self.assertEqual(self.detector._select_target(), outside)

  def test_current_target_stays_for_small_difference_but_can_switch(self):
    current = self.person(2, buriedness=10)
    other = self.person(3, buriedness=9)
    self.detector._result = current
    self.detector.calculate()
    self.assertEqual(self.detector.get_target_entity_id(), current)
    self.people[1].get_buriedness_property().set_value(2)
    self.detector.calculate()
    self.assertEqual(self.detector.get_target_entity_id(), other)

  def test_completed_or_dead_target_is_replaced(self):
    old = self.person(2)
    other = self.person(3)
    for property_name in ('get_hp_property', 'get_buriedness_property'):
      with self.subTest(property_name=property_name):
        self.people[0].get_hp_property().set_value(10000)
        self.people[0].get_buriedness_property().set_value(5)
        getattr(self.people[0], property_name)().set_value(0)
        self.detector._result = old
        self.detector.calculate()
        self.assertEqual(self.detector.get_target_entity_id(), other)

  def test_missing_damage_and_unknown_distance(self):
    target = self.person(2, damage=None)
    self.assertEqual(self.detector._select_target(), target)
    self.distances[target] = -1
    self.detector.calculate()
    self.assertIsNone(self.detector.get_target_entity_id())

  def test_cost_is_finite_and_continuous_at_feasibility_boundary(self):
    cost = self.detector._rescue_cost
    self.assertTrue(math.isfinite(cost(1, 100, 50, 12)))
    self.assertAlmostEqual(cost(1700, 100, 5, 12), cost(1700, 100, 5.000001, 12), places=5)

  def add_brigades(self, count):
    for ident in range(1, count + 1):
      brigade = FireBrigade(ident)
      brigade.get_position_property().set_value(EntityID(200 + ident))
      brigade.get_hp_property().set_value(10000)
      brigade.get_buriedness_property().set_value(0)
      self.brigades.append(brigade)

  def test_six_brigades_split_into_two_teams_of_three(self):
    self.add_brigades(6)
    first = self.person(20, buriedness=35)
    second = self.person(21, buriedness=35)
    assignments = []
    for brigade in self.brigades:
      self.detector._agent_info.get_entity_id.return_value = brigade.get_entity_id()
      self.detector._result = second  # 個別の継続加点で割り当てが変わらない
      assignments.append(self.detector._select_target())
    self.assertEqual(assignments, [first] * 3 + [second] * 3)
    self.brigades.reverse()
    self.people.reverse()
    self.detector._agent_info.get_entity_id.return_value = EntityID(1)
    self.assertEqual(self.detector._select_target(), first)

  def test_fourth_brigade_does_not_join_full_target(self):
    self.add_brigades(4)
    self.person(20, buriedness=35)
    self.detector._agent_info.get_entity_id.return_value = EntityID(4)
    self.assertIsNone(self.detector._select_target())

  def test_late_brigades_are_not_counted_as_rescuers(self):
    self.add_brigades(3)
    target = self.person(20, buriedness=5)
    self.detector._world_info.get_distance.side_effect = (
      lambda start, end: 0 if start == EntityID(1) else 3000000
    )
    self.assertEqual(self.detector._select_target(), target)
    self.detector._agent_info.get_entity_id.return_value = EntityID(2)
    self.assertIsNone(self.detector._select_target())

  def test_dead_and_buried_brigades_do_not_fill_slots(self):
    self.add_brigades(5)
    target = self.person(20, buriedness=35)
    self.brigades[1].get_hp_property().set_value(0)
    self.brigades[2].get_buriedness_property().set_value(10)
    self.detector._agent_info.get_entity_id.return_value = EntityID(5)
    self.assertEqual(self.detector._select_target(), target)

  def test_teams_reassign_after_rescue(self):
    self.add_brigades(3)
    self.person(20, buriedness=35)
    second = self.person(21, buriedness=35)
    self.detector.calculate()
    self.people[0].get_buriedness_property().set_value(0)
    self.detector.calculate()
    self.assertEqual(self.detector.get_target_entity_id(), second)

  def test_staggered_arrivals_reduce_rescue_time(self):
    estimate = self.detector._team_rescue_time
    self.assertEqual(estimate(35, [0, 0, 0]), 12)
    self.assertEqual(estimate(35, [0, 5, 10]), 17)
    self.assertEqual(estimate(5, [0, 10, 20]), 5)

  def test_urgent_civilian_precedes_ambulance_in_both_modes(self):
    urgent = self.person(20, hp=1800, damage=100)
    self.person(21, buriedness=1, kind=AmbulanceTeam)
    self.assertEqual(self.detector._select_target(), urgent)
    self.add_brigades(3)
    self.assertEqual(self.detector._select_target(), urgent)

  def test_ambulance_precedes_nonurgent_civilian_in_both_modes(self):
    self.person(20, buriedness=1)
    ambulance = self.person(21, buriedness=35, kind=AmbulanceTeam)
    self.assertEqual(self.detector._select_target(), ambulance)
    self.add_brigades(3)
    self.assertEqual(self.detector._select_target(), ambulance)

  def test_impossible_civilian_does_not_block_ambulance(self):
    self.person(20, hp=100, damage=100)
    ambulance = self.person(21, kind=AmbulanceTeam)
    self.assertEqual(self.detector._select_target(), ambulance)

  def test_ambulance_requires_no_transport_and_releases_after_unburying(self):
    ambulance = self.person(21, hp=1000, damage=100, kind=AmbulanceTeam)
    self.assertEqual(self.detector._target_priority(self.people[0], 5, 0)[0], 1)
    self.assertEqual(self.detector._select_target(), ambulance)
    self.people[0].get_buriedness_property().set_value(0)
    self.detector.calculate()
    self.assertIsNone(self.detector.get_target_entity_id())

  def test_dead_ambulance_is_not_targeted(self):
    self.person(21, hp=0, kind=AmbulanceTeam)
    self.assertIsNone(self.detector._select_target())


if __name__ == '__main__':
  unittest.main()
