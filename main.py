import asyncio
from core.environment import Environment
from core.simulation import SimulationManager
from core.interface import GridVisualizer


async def main():
    try:
        # Initialize environment and visualization
        env = Environment(config_path="config.yaml")
        visualizer = GridVisualizer(env.size)

        # Create and setup simulation manager
        sim_manager = SimulationManager(env, visualizer)
        await sim_manager.initialize_agents()

        # Run simulation
        await sim_manager.run()

    except Exception as e:
        print(f"\nFatal error: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nSimulation interrupted by user")
