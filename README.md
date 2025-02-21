# Waste Collection System

This assignment was part of the **Introduction to Intelligent and Autonomous Systems** course. This project involved the development of a multi-agent system simulating autonomous waste collection using intelligent bins and trucks. It was developed using Python and SPADE.

## Key Components

### Agents

- **bin_agent.py**: Monitors waste levels, requests collections using Contract Net Protocol
- **truck_agent.py**: Manages waste collection, fuel levels, and bids for collection tasks

### Core

- **environment.py**: Handles grid system, traffic events, and rush hour multipliers 
- **simulation.py**: Controls agent creation, simulation time, and statistics collection
- **interface.py**: Real-time visualization of agents, bins, and system status

### Configuration and Results

- **config.yaml**: Contains all simulation parameters (agents, thresholds, capacities, etc.)
- **simulation_results.csv**: Includes simulation runs with different configurations for analysis

## Running the Simulation

- python main.py

@FMSCarvalho (Filipe Carvalho), @luanalegi (Luana Letra), @pazzolini (Vítor Ferreira).
