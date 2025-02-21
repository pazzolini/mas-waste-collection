import asyncio
from typing import List, Dict
import random
import time
import os
import csv
from agents.truck_agent import TruckAgent
from agents.bin_agent import BinAgent


class SimulationManager:
    def __init__(self, env, visualizer=None):
        self.env = env
        self.visualizer = visualizer
        self.trucks: List[TruckAgent] = []
        self.bins: List[BinAgent] = []
        self.start_time = None
        self.simulation_days = 7
        self.simulation_hours = self.simulation_days * 24

    def format_time(self, decimal_time):
        """Convert decimal time to HH:MM format"""
        hours = int(decimal_time)
        minutes = int((decimal_time % 1) * 60)
        return f"{hours:02d}:{minutes:02d}"

    async def initialize_agents(self, random_seed: int = 8):
        """Initialize all agents with proper error handling"""
        random.seed(random_seed)

        # Get counts from config
        num_bins = self.env.config['agents']['counts']['bins']
        num_trucks = self.env.config['agents']['counts']['trucks']
        min_distance = self.env.config['agents']['bin']['min_distance']

        # Initialize bins
        for i in range(num_bins):
            while True:
                pos = (random.randint(0, self.env.size - 1), random.randint(0, self.env.size - 1))
                if pos != self.env.depot["position"] and pos not in [station["position"] for station in
                                                                     self.env.fuel_stations]:
                    if not self.bins or all(
                            max(abs(pos[0] - b.position[0]), abs(pos[1] - b.position[1])) >= min_distance
                            for b in self.bins
                    ):
                        break

            bin_agent = BinAgent(f"bin{i + 1}@localhost", "password", self.env, position=pos)
            await bin_agent.start()
            self.bins.append(bin_agent)

        # Initialize trucks
        for i in range(num_trucks):
            truck_agent = TruckAgent(f"truck{i + 1}@localhost", "password", self.env)
            await truck_agent.start()
            self.trucks.append(truck_agent)

        random.seed()
        return self.trucks, self.bins

    async def run_simulation_step(self, current_hour):
        """Run a single step of the simulation"""
        self.env.step_time()
        time_of_day = self.env.current_time

        if self.visualizer:
            self.visualizer.update_display(self.env, self.trucks, self.bins)

        # Update status display
        current_day = (current_hour // 24) + 1
        formatted_time = self.format_time(time_of_day)
        status = "🌙\n" if (20 <= time_of_day or time_of_day <= 6) else ""
        status += " ⚠️\n" if (7 <= time_of_day <= 9) or (17 <= time_of_day <= 19) else ""

        print(f"\rDay {current_day}/7 - Time: {formatted_time} {status}", end="", flush=True)

    def collect_statistics(self) -> Dict:
        """Collect essential simulation statistics including malfunctions and configuration"""
        stats = {
            # Configuration parameters
            'number_of_trucks': self.env.config['agents']['counts']['trucks'],
            'number_of_bins': self.env.config['agents']['counts']['bins'],
            'bin_threshold': self.env.config['agents']['bin']['threshold'],
            'truck_waste_capacity': self.env.config['agents']['truck']['waste']['capacity'],
            'truck_waste_threshold': self.env.config['agents']['truck']['waste']['threshold'],
            'truck_fuel_capacity': self.env.config['agents']['truck']['fuel']['capacity'],
            'truck_fuel_threshold': self.env.config['agents']['truck']['fuel']['threshold'],

            # Runtime statistics
            'simulation_time': time.time() - self.start_time,
            'simulation_days': self.simulation_days,
            'total_collections': sum(t.total_collections for t in self.trucks if t.is_alive()),
            'total_distance': sum(t.total_distance for t in self.trucks if t.is_alive()),
            'total_fuel_used': sum(t.total_fuel_used for t in self.trucks if t.is_alive()),
            'total_waste_generated': sum(b.total_waste_generated for b in self.bins if b.is_alive()),
            'total_overflow_incidents': sum(b.overflow_incidents for b in self.bins if b.is_alive()),
            'total_traffic_events': self.env.get_event_statistics()['total_events'],
            'total_malfunctions': sum(t.malfunction_count for t in self.trucks if t.is_alive()),
            'total_refuel_count': sum(t.refuel_count for t in self.trucks if t.is_alive()),
            'total_depot_returns': sum(t.depot_returns for t in self.trucks if t.is_alive()),
            'total_mission_costs': sum(b.total_mission_costs for b in self.bins if b.is_alive())
        }
        return stats

    async def save_statistics(self):
        """Save statistics to CSV and print summary"""
        stats = self.collect_statistics()

        # Print summary
        print("\n====== Simulation Summary ======")
        print(f"Configuration:")
        print(f"Number of trucks: {stats['number_of_trucks']}")
        print(f"Number of bins: {stats['number_of_bins']}")
        print(f"Bin collection threshold: {stats['bin_threshold'] * 100}%")
        print(f"Truck waste capacity: {stats['truck_waste_capacity']} units")
        print(f"Truck waste threshold: {stats['truck_waste_threshold'] * 100}%")
        print(f"Truck fuel capacity: {stats['truck_fuel_capacity']}L")
        print(f"Truck fuel threshold: {stats['truck_fuel_threshold'] * 100}%")
        print("\nPerformance Statistics:")
        print(f"Total simulation time: {stats['simulation_time']:.2f} seconds")
        print(f"Total collections: {stats['total_collections']}")
        print(f"Total distance traveled: {stats['total_distance']:.2f} units")
        print(f"Total fuel used: {stats['total_fuel_used']:.2f}L")
        print(f"Total mission costs: {stats['total_mission_costs']:.2f}")
        print(f"Total waste generated: {stats['total_waste_generated']:.2f}")
        print(f"Total overflow incidents: {stats['total_overflow_incidents']}")
        print(f"Total traffic events: {stats['total_traffic_events']}")
        print(f"Total truck malfunctions: {stats['total_malfunctions']}")
        print(f"Total refueling stops: {stats['total_refuel_count']}")
        print(f"Total depot returns: {stats['total_depot_returns']}")

        # Save to CSV
        csv_filename = "simulation_results.csv"
        file_exists = os.path.isfile(csv_filename)

        with open(csv_filename, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=stats.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(stats)

    async def cleanup(self):
        """Clean up simulation resources"""
        if self.visualizer:
            self.visualizer.close()

        for agent in self.trucks + self.bins:
            if agent.is_alive():
                await agent.stop()

    async def run(self):
        """Run the complete simulation"""
        self.start_time = time.time()
        seconds_per_hour = self.env.config['time']['real_seconds_per_hour']

        print("\nSimulation started!")
        print(f"Time scale: {seconds_per_hour} real seconds = 1 simulation hour")
        print(f"Depot position: {self.env.depot['position']}")

        try:
            for current_hour in range(self.simulation_hours):
                cycle_start = time.time()

                await self.run_simulation_step(current_hour)

                # Maintain correct timescale
                elapsed = time.time() - cycle_start
                await asyncio.sleep(max(0, seconds_per_hour - elapsed))

        except KeyboardInterrupt:
            print("\n\nSimulation stopped by user")
        finally:
            await self.save_statistics()
            await self.cleanup()
            print("\nSimulation ended!")