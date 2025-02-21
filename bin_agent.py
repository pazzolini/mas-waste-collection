from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message
from spade.template import Template
import json
import random
import time
from typing import Tuple, Any, Dict, Optional
import yaml
import asyncio


class BinAgent(Agent):
    def __init__(self, jid: str, password: str, environment: Any, position: Tuple[int, int],
                 config_path: str = "config.yaml"):
        super().__init__(jid, password)
        self.env = environment
        self.position = position

        # Load configuration
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            self.config = config['agents']['bin']

            # Get number of trucks from config
            num_trucks = config['agents']['counts']['trucks']
            self.truck_jids = [f"truck{i}@localhost" for i in range(1, num_trucks + 1)]

        except Exception as e:
            print(f"Error loading config for bin {jid}: {e}")
            raise

        # Initialize parameters from config
        self.monitor_period = self.config['monitor_period']
        self.capacity = self.config['capacity']
        self.threshold = self.config['threshold']
        self.current_level = 0

        # Proposal handling
        self.waiting_for_collection = False
        self.cfp_start_time: Optional[float] = None
        self.proposal_timeout = 5
        self.proposals: Dict[str, float] = {}
        self.trucks_responded = set()
        self.selected_truck: Optional[str] = None
        self.last_collection_time: Optional[float] = None

        # Statistics
        self.total_collections_received = 0
        self.total_wait_time = 0
        self.total_waste_generated = 0
        self.overflow_incidents = 0
        self.total_mission_costs = 0

        # Initialize behaviors as instance attributes
        self.monitor_behaviour = None
        self.handle_proposals = None

    def reset_collection_state(self):
        """Reset all collection-related state"""
        self.waiting_for_collection = False
        self.cfp_start_time = None
        self.proposals.clear()
        self.trucks_responded.clear()
        self.selected_truck = None

    def record_collection(self):
        """Record a successful collection"""
        self.total_collections_received += 1

    def record_waste_generation(self, amount: float):
        """Record waste generation"""
        self.total_waste_generated += amount
        if self.current_level >= self.capacity:
            self.overflow_incidents += 1

    class MonitorLevel(PeriodicBehaviour):
        async def run(self):
            try:
                if self.agent.waiting_for_collection:
                    # Check if we've waited too long for proposals
                    if (self.agent.cfp_start_time and
                            time.time() - self.agent.cfp_start_time >= self.agent.proposal_timeout):
                        await self.handle_proposal_timeout()
                    return

                # Consider time of day for fill rate
                time_multiplier = 0.5 if 0 <= self.agent.env.current_time <= 6 else 1.0
                fill_rate = random.uniform(
                    self.agent.config['fill_rate']['min'],
                    self.agent.config['fill_rate']['max']
                ) * time_multiplier

                # Calculate new level but don't exceed capacity
                new_level = self.agent.current_level + fill_rate
                if new_level > self.agent.capacity:
                    self.agent.current_level = self.agent.capacity
                    print(f"Bin {self.agent.jid} is full! Level: {self.agent.current_level:.2f}/{self.agent.capacity}")
                else:
                    self.agent.current_level = new_level
                    print(f"Bin {self.agent.jid} level: {self.agent.current_level:.2f}/{self.agent.capacity}")

                # Record waste generation
                self.agent.record_waste_generation(fill_rate)

                if self.agent.current_level >= self.agent.capacity * self.agent.threshold:
                    print(f"Bin {self.agent.jid} needs collection! Level: {self.agent.current_level:.2f}")
                    await self.initiate_cfp()

            except Exception as e:
                print(f"Error in MonitorLevel for bin {self.agent.jid}: {e}")

        async def handle_proposal_timeout(self):
            """Handle timeout for proposal collection"""
            print(f"Bin {self.agent.jid} proposal collection timeout")
            if not self.agent.proposals:
                print(f"Bin {self.agent.jid} received no proposals, will try again later")
                self.agent.reset_collection_state()
                return
            await self.agent.handle_proposals.select_best_proposal()

        async def initiate_cfp(self):
            """Initiate Call for Proposals"""
            try:
                self.agent.waiting_for_collection = True
                self.agent.cfp_start_time = time.time()
                self.agent.proposals.clear()
                self.agent.trucks_responded.clear()
                self.agent.selected_truck = None

                # Send CFP to all trucks
                for truck_jid in self.agent.truck_jids:
                    msg = Message(to=truck_jid)
                    msg.set_metadata("performative", "cfp")
                    data = {
                        "position": list(self.agent.position),
                        "level": self.agent.current_level,
                        "time": self.agent.env.current_time,
                        "last_collection_time": self.agent.last_collection_time
                    }
                    msg.body = json.dumps(data)
                    await self.send(msg)
                    print(f"Bin {self.agent.jid} sent CFP to {truck_jid} for collection at time {self.agent.env.current_time}")
            except Exception as e:
                print(f"Error initiating CFP for bin {self.agent.jid}: {e}")
                self.agent.reset_collection_state()

    class HandleProposals(CyclicBehaviour):
        async def run(self):
            try:
                msg = await self.receive(timeout=10)
                if not msg:
                    return

                performative = msg.metadata.get("performative")
                if not performative:
                    print(f"Received message without performative from {msg.sender}")
                    return

                if performative == "propose":
                    await self.handle_proposal(msg)
                elif performative == "inform":
                    await self.handle_inform(msg)
                elif performative == "refuse":
                    await self.handle_refuse(msg)

            except Exception as e:
                print(f"Error in HandleProposals for bin {self.agent.jid}: {e}")

        async def handle_proposal(self, msg):
            """Handle proposal messages"""
            sender = str(msg.sender)
            if sender not in self.agent.trucks_responded and not self.agent.selected_truck:
                try:
                    cost = float(msg.body)
                    print(f"Bin {self.agent.jid} received proposal from {sender}: Cost = {cost}")
                    self.agent.proposals[sender] = cost
                    self.agent.trucks_responded.add(sender)

                    if len(self.agent.trucks_responded) == len(self.agent.truck_jids):
                        await self.select_best_proposal()
                except ValueError:
                    print(f"Invalid cost value received from {sender}")

        async def handle_refuse(self, msg):
            """Handle refuse messages"""
            sender = str(msg.sender)
            try:
                if msg.body == "MALFUNCTIONED":
                    print(f"Bin {self.agent.jid} received refusal from {sender} - truck is under repair")
                else:
                    print(f"Bin {self.agent.jid} received refusal from {sender} - {msg.body}")

                if sender in self.agent.proposals:
                    del self.agent.proposals[sender]
                self.agent.trucks_responded.add(sender)

                if len(self.agent.trucks_responded) == len(self.agent.truck_jids):
                    await self.select_best_proposal()
            except Exception as e:
                print(f"Error handling refusal from {sender}: {e}")

        async def handle_inform(self, msg):
            """Handle inform messages"""
            sender = str(msg.sender)
            try:
                data = json.loads(msg.body)

                if "status" in data:
                    if data["status"] == "TRUCK_MALFUNCTION":
                        print(f"Bin {self.agent.jid}: Truck {sender} malfunctioned during collection")
                        print(f"Repair time: {data['repair_time']:.2f} hours")
                        # Reset state but maintain waste level
                        self.agent.reset_collection_state()
                        # Initiate new CFP after a short delay
                        await asyncio.sleep(1)
                        await self.initiate_new_cfp()

                    elif data["status"] == "COLLECTION_COMPLETE":
                        print(f"Bin {self.agent.jid} has been emptied and will resume filling")
                        self.agent.current_level = 0
                        self.agent.last_collection_time = self.agent.env.current_time
                        self.agent.record_collection()
                        self.agent.reset_collection_state()

            except Exception as e:
                print(f"Error handling inform message from {sender}: {e}")

        async def initiate_new_cfp(self):
            """Initiate a new CFP if a truck malfunctions"""
            try:
                print(f"Bin {self.agent.jid} initiating new CFP after truck malfunction")
                self.agent.waiting_for_collection = True
                self.agent.cfp_start_time = time.time()
                self.agent.proposals.clear()
                self.agent.trucks_responded.clear()
                self.agent.selected_truck = None

                for truck_jid in self.agent.truck_jids:
                    msg = Message(to=truck_jid)
                    msg.set_metadata("performative", "cfp")
                    data = {
                        "position": list(self.agent.position),
                        "level": self.agent.current_level,
                        "time": self.agent.env.current_time,
                        "last_collection_time": self.agent.last_collection_time,
                        "is_retry": True
                    }
                    msg.body = json.dumps(data)
                    await self.send(msg)
                print(f"Bin {self.agent.jid} sent new CFPs after malfunction")
            except Exception as e:
                print(f"Error initiating new CFP after malfunction: {e}")
                self.agent.reset_collection_state()

        async def select_best_proposal(self):
            """Select the best proposal considering costs and randomization"""
            if not self.agent.proposals or self.agent.selected_truck:
                if not self.agent.proposals:
                    print(f"Bin {self.agent.jid} has no valid proposals, will try again later")
                self.agent.reset_collection_state()
                return

            try:
                # Group proposals by cost
                proposals_by_cost = {}
                for truck_jid, cost in self.agent.proposals.items():
                    cost_key = round(cost, 2)
                    if cost_key not in proposals_by_cost:
                        proposals_by_cost[cost_key] = []
                    proposals_by_cost[cost_key].append(truck_jid)

                # Get the lowest cost
                min_cost = min(proposals_by_cost.keys())
                selected_truck = random.choice(proposals_by_cost[min_cost])
                self.agent.selected_truck = selected_truck

                # Add this line to track the cost
                self.agent.total_mission_costs += min_cost

                print(f"Bin {self.agent.jid} selecting proposal from {selected_truck}")

                # First send rejections to non-selected trucks
                await self.send_rejections(selected_truck, min_cost)

                # Then send acceptance to selected truck
                await self.send_acceptance(selected_truck)

            except Exception as e:
                print(f"Error selecting best proposal for bin {self.agent.jid}: {e}")
                self.agent.reset_collection_state()

        async def send_rejections(self, selected_truck: str, selected_cost: float):
            """Send reject-proposal messages to all non-selected trucks"""
            try:
                for truck_jid in self.agent.proposals.keys():
                    if truck_jid != selected_truck:
                        reject_msg = Message(to=truck_jid)
                        reject_msg.set_metadata("performative", "reject-proposal")
                        data = {
                            "reason": "better_proposal_selected",
                            "selected_cost": selected_cost,
                            "your_cost": self.agent.proposals[truck_jid]
                        }
                        reject_msg.body = json.dumps(data)
                        await self.send(reject_msg)
                        print(f"Bin {self.agent.jid} sent rejection to {truck_jid}")
            except Exception as e:
                print(f"Error sending rejections: {e}")

        async def send_acceptance(self, selected_truck: str):
            """Send acceptance message to selected truck"""
            try:
                accept_msg = Message(to=selected_truck)
                accept_msg.set_metadata("performative", "accept-proposal")
                data = {
                    "position": list(self.agent.position),
                    "level": self.agent.current_level,
                    "time": self.agent.env.current_time
                }
                accept_msg.body = json.dumps(data)
                await self.send(accept_msg)
                print(f"Bin {self.agent.jid} accepted proposal from {selected_truck}")
            except Exception as e:
                print(f"Error sending acceptance to {selected_truck}: {e}")
                self.agent.reset_collection_state()

    async def setup(self):
        print(f"Bin {self.jid} starting at position {self.position}")

        # Create templates for message filtering
        propose_template = Template()
        propose_template.set_metadata("performative", "propose")

        inform_template = Template()
        inform_template.set_metadata("performative", "inform")

        refuse_template = Template()
        refuse_template.set_metadata("performative", "refuse")

        # Initialize and store behaviors
        self.monitor_behaviour = self.MonitorLevel(period=self.monitor_period)
        self.handle_proposals = self.HandleProposals()

        # Add behaviors with templates
        self.add_behaviour(self.monitor_behaviour)
        self.add_behaviour(self.handle_proposals, template=propose_template | inform_template | refuse_template)
