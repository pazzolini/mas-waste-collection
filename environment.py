import random
import yaml
from dataclasses import dataclass
from typing import Tuple, List

class Environment:
    def __init__(self, config_path: str = "config.yaml"):
        # Load configuration
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Basic parameters
        self.size = self.config['grid']['size']
        self.current_time = 0
        self.current_day = 1

        # Initialize locations
        self.depot = {
            "position": tuple(self.config['locations']['depot']['position'])
        }
        self.fuel_stations = [
            {"position": tuple(station['position'])}
            for station in self.config['locations']['fuel_stations']
        ]

        # traffic events
        self.active_events: List[TrafficEvent] = []
        self.total_events = 0

    def calculate_distance(self, start: Tuple[int, int], end: Tuple[int, int]) -> int:
        """Calculate Manhattan distance between two points"""
        return abs(end[0] - start[0]) + abs(end[1] - start[1])

    def is_rush_hour(self) -> bool:
        """Simple check for rush hour periods"""
        morning_rush = (7 <= self.current_time <= 9)
        evening_rush = (17 <= self.current_time <= 19)
        return morning_rush or evening_rush

    def get_rush_hour_multiplier(self) -> float:
        """Get traffic multiplier for rush hours"""
        if not self.is_rush_hour():
            return 1.0

        if 7 <= self.current_time <= 9:
            return self.config['time']['rush_hours']['morning']['traffic_multiplier']
        else:  # 17-19
            return self.config['time']['rush_hours']['evening']['traffic_multiplier']

    def check_traffic_event(self, position: Tuple[int, int]) -> float:
        """Check if position is affected by any traffic event"""
        for event in self.active_events:
            if self.calculate_distance(position, event.position) <= 2:
                return event.multiplier
        return 1.0

    def get_travel_cost(self, start: Tuple[int, int], end: Tuple[int, int]) -> float:
        """Calculate travel cost considering rush hour and events"""
        base_distance = self.calculate_distance(start, end)

        # Get the highest applicable multiplier
        rush_multiplier = self.get_rush_hour_multiplier()
        event_multiplier = max(
            self.check_traffic_event(start),
            self.check_traffic_event(end)
        )

        # Use the highest multiplier effect
        final_multiplier = max(rush_multiplier, event_multiplier)

        return base_distance * final_multiplier

    def step_time(self) -> None:
        """Advance time by one hour"""
        self.current_time += 1

        # Handle day transition
        if self.current_time >= 24:
            self.current_time = 0
            self.current_day += 1

        # Update active events
        self.active_events = [
            event for event in self.active_events
            if event.duration > 0
        ]

        # Decrease duration of active events
        for event in self.active_events:
            event.duration -= 1

        # Generate new events
        self._generate_random_events()

    def _generate_random_events(self) -> None:
        """Random event generation"""
        # Only generate events during daytime (6-20)
        if not (6 <= self.current_time <= 20):
            return

        # Probability check
        if random.random() < self.config['random_events']['accident_probability']:
            self._add_traffic_event('accident')
        if random.random() < self.config['random_events']['roadwork_probability']:
            self._add_traffic_event('roadwork')

    def _add_traffic_event(self, event_type: str) -> None:
        """Add a new traffic event"""
        # Find a valid position
        while True:
            pos = (random.randint(0, self.size - 1), random.randint(0, self.size - 1))
            if (pos != self.depot["position"] and
                    pos not in [station["position"] for station in self.fuel_stations]):
                break

        # Set event properties
        duration = random.randint(2, 4)  # Simplified duration (2-4 hours)
        multiplier = self.config['traffic_events'][event_type]['traffic_multiplier']

        # Create and add event
        new_event = TrafficEvent(
            position=pos,
            duration=duration,
            multiplier=multiplier
        )

        self.active_events.append(new_event)
        self.total_events += 1
        print(f"New {event_type} at {pos}, duration: {duration}h, multiplier: {multiplier}x")

    def get_event_statistics(self) -> dict:
        """Simple event statistics"""
        return {
            'total_events': self.total_events,
            'active_events': len(self.active_events)
        }

@dataclass
class TrafficEvent:
    """Simplified traffic event in the simulation"""
    position: Tuple[int, int]
    duration: int
    multiplier: float
