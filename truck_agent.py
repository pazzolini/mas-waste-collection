from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
import json
import asyncio
import random
from typing import Tuple, Any
import yaml


class TruckAgent(Agent):
    def __init__(self, jid: str, password: str, environment: Any, config_path: str = "config.yaml"):
        super().__init__(jid, password)
        self.env = environment
        self.position = environment.depot["position"]

        # Load configuration
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        self.config = config['agents']['truck']

        # Initialize parameters from config
        self.speed = self.config['speed']
        self.fuel_level = self.config['fuel']['capacity']
        self.fuel_consumption = self.config['fuel']['consumption']
        self.fuel_threshold = self.config['fuel']['capacity'] * self.config['fuel']['threshold']
        self.waste_capacity = self.config['waste']['capacity']
        self.current_waste = 0
        self.busy = False
        self.current_bin = None
        self.malfunction_probability = self.config['malfunction']['probability']
        self.malfunction_min_duration = self.config['malfunction']['duration']['min']
        self.malfunction_max_duration = self.config['malfunction']['duration']['max']

        # Statistics
        self.total_collections = 0
        self.total_distance = 0
        self.total_fuel_used = 0
        self.refuel_count = 0
        self.depot_returns = 0
        self.total_waste_collected = 0
        self.busy_time = 0
        self.service_start_time = None
        self.service_start_day = None
        self.malfunctioned = False
        self.malfunction_end_time = None
        self.malfunction_end_day = None
        self.malfunction_count = 0

    def find_nearest_fuel_station(self, current_pos: Tuple[int, int]) -> Tuple[Tuple[int, int], float]:
        """Find the nearest fuel station and return its position and distance"""
        nearest_station = None
        min_distance = float('inf')

        for station in self.env.fuel_stations:
            station_pos = station["position"]
            distance = self.env.get_travel_cost(current_pos, station_pos)

            if distance < min_distance:
                min_distance = distance
                nearest_station = station_pos

        return nearest_station, min_distance

    def record_collection(self):
        """Record collection details"""
        self.total_collections += 1
        self.total_waste_collected += self.current_waste

    def record_refuel(self, amount: float):
        """Record refueling event"""
        self.refuel_count += 1
        self.total_fuel_used += amount

    def start_service(self):
        """Record service start time"""
        if not self.busy:
            self.busy = True
            self.service_start_time = self.env.current_time
            self.service_start_day = self.env.current_day
            print(f"Truck {self.jid} started service at day {self.service_start_day}, time {self.service_start_time}")

    def end_service(self):
        """Record service end time"""
        if self.service_start_time is not None:
            current_time = self.env.current_time
            current_day = self.env.current_day

            # Calculate total hours including days passed
            hours_from_days = (current_day - self.service_start_day) * 24
            if current_time < self.service_start_time:
                elapsed_time = (24 - self.service_start_time) + current_time
            else:
                elapsed_time = current_time - self.service_start_time

            total_elapsed = hours_from_days + elapsed_time
            self.busy_time += total_elapsed
            print(f"Truck {self.jid} ended service: +{total_elapsed:.2f} hours (Total: {self.busy_time:.2f})")

            self.service_start_time = None
            self.service_start_day = None
        self.busy = False

    async def check_malfunction(self) -> bool:
        """Check if truck malfunctions"""
        if not self.malfunctioned and random.random() < self.malfunction_probability:
            self.malfunction_count += 1
            self.malfunctioned = True

            repair_duration = random.uniform(
                self.malfunction_min_duration,
                self.malfunction_max_duration
            )

            # Store both day and time for repair end
            self.malfunction_end_day = self.env.current_day
            self.malfunction_end_time = self.env.current_time + repair_duration

            # Handle day wrap-around
            if self.malfunction_end_time >= 24:
                self.malfunction_end_day += self.malfunction_end_time // 24
                self.malfunction_end_time = self.malfunction_end_time % 24

            self.position = self.env.depot["position"]
            print(f"Truck {self.jid} has malfunctioned and returned to depot!")
            print(f"Expected repair time: {repair_duration:.2f} hours")
            print(f"Will be repaired on day {self.malfunction_end_day} at time {self.malfunction_end_time:.2f}")
            return True
        return False

    async def update_malfunction_status(self) -> bool:
        """Check if repair period is over"""
        if self.malfunctioned and self.malfunction_end_time is not None:
            current_time = self.env.current_time
            current_day = self.env.current_day

            # Check if we've reached or passed the repair end time
            if (current_day > self.malfunction_end_day or
                    (current_day == self.malfunction_end_day and
                     current_time >= self.malfunction_end_time)):
                self.malfunctioned = False
                self.malfunction_end_time = None
                self.malfunction_end_day = None
                self.service_start_time = None
                print(f"🔧 Truck {self.jid} has been repaired and is ready for new tasks!")
                return True
            else:
                # Calculate remaining time including days
                remaining_days = self.malfunction_end_day - current_day
                remaining_hours = self.malfunction_end_time - current_time
                if remaining_hours < 0:
                    remaining_days -= 1
                    remaining_hours = 24 + remaining_hours

                total_remaining = remaining_days * 24 + remaining_hours
                print(f"⚠️ Truck {self.jid} still under repair. {total_remaining:.2f} hours remaining")
        return False

    class HandleCFP(CyclicBehaviour):
        async def run(self):
            """Main run loop for handling Call for Proposals"""
            # Update truck status first
            await self.agent.update_malfunction_status()

            # Wait for incoming message
            msg = await self.receive(timeout=10)
            if not msg:
                return

            sender = str(msg.sender)

            # Check truck availability
            if not await self._check_truck_availability(sender):
                return

            # Process the CFP
            await self._process_cfp(msg, sender)

        async def _check_truck_availability(self, sender: str):
            """Check if truck is available for new tasks"""
            # Check for malfunction
            if self.agent.malfunctioned:
                remaining_repair = self.agent.malfunction_end_time - self.agent.env.current_time
                print(f"🚫 Truck {self.agent.jid} is under repair at depot for {remaining_repair:.2f} more hours, "
                      f"refusing request from {sender}")
                await self.send_refusal(sender, "MALFUNCTIONED")
                return False

            # Check if busy
            if self.agent.busy:
                print(f"Truck {self.agent.jid} is busy with {self.agent.current_bin}, "
                      f"refusing request from {sender}")
                await self.send_refusal(sender, "BUSY")
                return False

            return True

        async def _process_cfp(self, msg: Message, sender: str):
            """Process the Call for Proposal message"""
            print(f"Truck {self.agent.jid} received CFP from {sender}")

            try:
                # Parse message data
                bin_data = self._parse_bin_data(msg.body)
                if not bin_data:
                    return

                if not await self._check_waste_capacity(bin_data['waste_level'], sender):
                    return

                # Calculate mission cost
                total_cost = await self.calculate_mission_cost(bin_data['position'], bin_data['waste_level'])

                # Handle response
                await self._handle_cost_response(total_cost, sender)

            except Exception as e:
                print(f"Truck {self.agent.jid} error processing CFP: {str(e)}")

        def _parse_bin_data(self, msg_body: str):
            """Parse bin data from message body"""
            data = json.loads(msg_body)
            return {
                'position': (int(data["position"][0]), int(data["position"][1])),
                'waste_level': data["level"]
                }

        async def _check_waste_capacity(self, waste_level: float, sender: str):
            """Check if truck has enough waste capacity"""
            if self.agent.current_waste + waste_level > self.agent.waste_capacity:
                print(f"Truck {self.agent.jid} cannot accept job - waste capacity full")
                await self.send_refusal(sender, "FULL")
                return False
            return True

        async def _handle_cost_response(self, total_cost: float, sender: str):
            """Handle the cost calculation response"""
            if total_cost == float('inf'):
                print(f"Truck {self.agent.jid} cannot reach bin - insufficient fuel")
                await self.send_refusal(sender, "NO_FUEL")
                return

            # Send proposal
            reply = Message(to=sender)
            reply.set_metadata("performative", "propose")
            reply.body = str(total_cost)
            await self.send(reply)
            print(f"Truck {self.agent.jid} sent proposal with cost {total_cost:.2f}")

        async def send_refusal(self, to: str, reason: str):
            """Send a refusal message"""
            refuse_msg = Message(to=to)
            refuse_msg.set_metadata("performative", "refuse")
            refuse_msg.body = reason
            await self.send(refuse_msg)

        async def calculate_mission_cost(self, bin_pos: Tuple[int, int], waste_level: float):
            """Calculate the total cost of the mission"""
            try:
                # Get relevant positions
                current_pos = self.agent.position
                depot_pos = self.agent.env.depot["position"]

                # Calculate base distance to bin
                dist_to_bin = self.agent.env.get_travel_cost(current_pos, bin_pos)
                total_distance = dist_to_bin

                # Check if depot visit will be needed
                waste_after_collection = self.agent.current_waste + waste_level
                waste_threshold = self.agent.waste_capacity * self.agent.config['waste']['threshold']
                if waste_after_collection >= waste_threshold:
                    dist_to_depot = self.agent.env.get_travel_cost(bin_pos, depot_pos)
                    total_distance += dist_to_depot

                # Check fuel requirements
                fuel_needed = total_distance * self.agent.fuel_consumption
                if fuel_needed > self.agent.fuel_level:
                    return float('inf')

                # Calculate final cost with waste penalty
                waste_factor = 1 + (self.agent.current_waste / self.agent.waste_capacity)
                return total_distance * waste_factor

            except Exception as e:
                print(f"Error calculating mission cost: {e}")
                return float('inf')

    class HandleAcceptance(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if not msg:
                return

            sender = str(msg.sender)

            print(f"Truck {self.agent.jid} proposal was accepted by {sender}")
            self.agent.busy = True
            self.agent.current_bin = sender

            try:
                data = json.loads(msg.body)
                bin_pos = (int(data["position"][0]), int(data["position"][1]))
                waste_level = data["level"]

                await self.execute_collection_mission(bin_pos, waste_level, sender)

            except Exception as e:
                print(f"Truck {self.agent.jid} error during collection: {str(e)}")
                # Inform bin of failure
                inform_msg = Message(to=sender)
                inform_msg.set_metadata("performative", "inform")
                inform_msg.body = "COLLECTION_FAILED"
                await self.send(inform_msg)
            finally:
                self.agent.busy = False
                self.agent.current_bin = None

        async def execute_collection_mission(self, bin_pos: Tuple[int, int], waste_level: float, sender: str):
            """Execute complete collection mission"""
            try:
                print(f"Truck {self.agent.jid} starting collection mission for {sender}")
                self.agent.start_service()
                initial_position = self.agent.position

                # Check for malfunction before starting travel
                if await self.agent.check_malfunction():
                    inform_msg = Message(to=sender)
                    inform_msg.set_metadata("performative", "inform")
                    inform_msg.body = json.dumps({
                        "status": "TRUCK_MALFUNCTION",
                        "repair_time": self.agent.malfunction_end_time - self.agent.env.current_time
                    })
                    await self.send(inform_msg)
                    raise Exception(f"Truck malfunction - returned to depot for repairs")

                # Check if refueling needed
                total_distance = self.agent.env.get_travel_cost(self.agent.position, bin_pos)

                if self.agent.current_waste + waste_level >= self.agent.waste_capacity * self.agent.config['waste'][
                    'threshold']:
                    total_distance += self.agent.env.get_travel_cost(bin_pos, self.agent.env.depot["position"])

                if (total_distance * self.agent.fuel_consumption > self.agent.fuel_level or
                        self.agent.fuel_level <= self.agent.fuel_threshold):
                    print(f"Truck {self.agent.jid} needs refueling before collection")
                    await self.refuel()

                # Travel to bin
                print(f"Truck {self.agent.jid} traveling to bin at {bin_pos}")
                await self.travel_to(bin_pos)

                # Collect waste
                print(f"Truck {self.agent.jid} collecting waste: {waste_level:.2f} units")
                await asyncio.sleep(1)  # Collection time
                self.agent.current_waste += waste_level

                # Record collection
                self.agent.record_collection()

                print(
                    f"Truck {self.agent.jid} collection complete. Capacity: {self.agent.current_waste:.2f}/{self.agent.waste_capacity}")

                # Inform bin of completion
                inform_msg = Message(to=sender)
                inform_msg.set_metadata("performative", "inform")
                inform_msg.body = json.dumps({
                    "status": "COLLECTION_COMPLETE"
                })
                await self.send(inform_msg)
                print(f"Truck {self.agent.jid} informed bin of completion")

                # Check if it needs to return to depot
                if self.agent.current_waste >= self.agent.waste_capacity * self.agent.config['waste']['threshold']:
                    print(
                        f"Truck {self.agent.jid} waste threshold reached ({self.agent.current_waste:.2f}), returning to depot")
                    await self.return_to_depot()
                else:
                    print(f"Truck {self.agent.jid} waiting at current position for new requests")

                # Update distance statistics
                distance_covered = self.agent.env.calculate_distance(initial_position, self.agent.position)
                self.agent.total_distance += distance_covered

                print(f"Truck {self.agent.jid} mission completed")

            except Exception as e:
                print(f"Truck {self.agent.jid} error during collection: {str(e)}")
                inform_msg = Message(to=sender)
                inform_msg.set_metadata("performative", "inform")
                if self.agent.malfunctioned:
                    inform_msg.body = json.dumps({
                        "status": "TRUCK_MALFUNCTION",
                        "repair_time": self.agent.malfunction_end_time - self.agent.env.current_time
                    })
                else:
                    inform_msg.body = json.dumps({
                        "status": "COLLECTION_FAILED"
                    })
                await self.send(inform_msg)
                raise

            finally:
                # Always end service and clear status
                self.agent.end_service()
                self.agent.busy = False
                self.agent.current_bin = None

        async def travel_to(self, destination: Tuple[int, int]):
            """Travel to destination with fuel monitoring"""
            distance = self.agent.env.get_travel_cost(self.agent.position, destination)
            travel_time = distance / self.agent.speed
            fuel_used = distance * self.agent.fuel_consumption

            if fuel_used > self.agent.fuel_level:
                raise Exception("Insufficient fuel for travel")

            self.agent.fuel_level -= fuel_used
            self.agent.total_fuel_used += fuel_used
            await asyncio.sleep(travel_time)
            self.agent.position = destination

            print(f"Truck {self.agent.jid} arrived at {destination}")

        async def refuel(self):
            """Refuel at nearest station"""
            station_pos, _ = self.agent.find_nearest_fuel_station(self.agent.position)
            print(f"Truck {self.agent.jid} heading to fuel station at {station_pos}")
            await self.travel_to(station_pos)
            await asyncio.sleep(1)
            old_fuel = self.agent.fuel_level
            fuel_added = self.agent.config['fuel']['capacity'] - old_fuel
            self.agent.fuel_level = self.agent.config['fuel']['capacity']
            self.agent.record_refuel(fuel_added)  # Record the refueling event
            print(f"Truck {self.agent.jid} refueled: {old_fuel:.2f}L -> {self.agent.fuel_level:.2f}L")

        async def return_to_depot(self):
            """Return to depot and empty waste"""
            print(f"Truck {self.agent.jid} returning to depot with {self.agent.current_waste:.2f} waste")
            await self.travel_to(self.agent.env.depot["position"])
            await asyncio.sleep(2)
            old_waste = self.agent.current_waste
            self.agent.current_waste = 0
            self.agent.depot_returns += 1  # Increment depot returns counter
            print(
                f"Truck {self.agent.jid} emptied {old_waste:.2f} waste at depot (Total returns: {self.agent.depot_returns})")

    class HandleRejection(CyclicBehaviour):
        """New behavior to handle proposal rejections"""
        async def run(self):
            msg = await self.receive(timeout=10)
            if not msg:
                return

            if msg.metadata.get("performative") == "reject-proposal":
                sender = str(msg.sender)
                try:
                    data = json.loads(msg.body)
                    print(f"Truck {self.agent.jid} proposal rejected by {sender}. Reason: {data.get('reason')}")

                    # Clear any stored state about this proposal
                    if self.agent.current_bin == sender:
                        self.agent.current_bin = None

                except Exception as e:
                    print(f"Error processing rejection from {sender}: {e}")

    async def setup(self):
        print(f"Truck {self.jid} starting at depot {self.position}")
        print(f"Initial fuel level: {self.fuel_level:.2f}L")
        print(f"Fuel threshold: {self.fuel_threshold:.2f}L")
        print(f"Waste capacity: {self.waste_capacity}L")

        # Create and add templates
        cfp_template = Template()
        cfp_template.set_metadata("performative", "cfp")

        accept_template = Template()
        accept_template.set_metadata("performative", "accept-proposal")

        reject_template = Template()
        reject_template.set_metadata("performative", "reject-proposal")

        # Add behaviors with templates
        self.add_behaviour(self.HandleCFP(), template=cfp_template)
        self.add_behaviour(self.HandleAcceptance(), template=accept_template)
        self.add_behaviour(self.HandleRejection(), template=reject_template)