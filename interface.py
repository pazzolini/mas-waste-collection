import pygame
from typing import Tuple


class GridVisualizer:
    def __init__(self, grid_size: int, cell_size: int = 50):
        """Initialize the grid visualizer"""
        pygame.init()
        self.grid_size = grid_size
        self.cell_size = cell_size

        # Calculate window size with padding and status bar
        self.padding = 20
        self.status_height = 40
        self.window_size = grid_size * cell_size + 2 * self.padding
        self.screen = pygame.display.set_mode((
            self.window_size,
            self.window_size + self.status_height
        ))
        pygame.display.set_caption("Waste Collection Simulation")

        # Define colors using RGB tuples
        self.COLORS = {
            'background': (240, 240, 240),  # Light gray
            'grid': (200, 200, 200),  # Gray
            'depot': (255, 0, 0),  # Red
            'fuel': (0, 255, 0),  # Green
            'bin': (0, 0, 255),  # Blue
            'truck_idle': (255, 140, 0),  # Orange
            'truck_busy': (200, 80, 0),  # Dark orange
            'text': (0, 0, 0),  # Black
            'status_bg': (50, 50, 50)  # Dark gray
        }

        # Initialize fonts
        self.font = pygame.font.Font(None, 24)
        self.small_font = pygame.font.Font(None, 20)

    def draw_grid(self):
        """Draw the basic grid"""
        self.screen.fill(self.COLORS['background'])

        # Draw grid lines
        for i in range(self.grid_size + 1):
            pos = i * self.cell_size + self.padding
            pygame.draw.line(self.screen, self.COLORS['grid'],
                             (pos, self.padding),
                             (pos, self.window_size - self.padding))
            pygame.draw.line(self.screen, self.COLORS['grid'],
                             (self.padding, pos),
                             (self.window_size - self.padding, pos))

    def draw_element(self, position: Tuple[int, int], color: Tuple[int, int, int],
                     text: str, info_text: str = None):
        """Draw a grid element"""
        x, y = position
        center = (x * self.cell_size + self.cell_size // 2 + self.padding,
                  y * self.cell_size + self.cell_size // 2 + self.padding)

        # Draw circle with outline
        pygame.draw.circle(self.screen, color, center, self.cell_size // 3)
        pygame.draw.circle(self.screen, (0, 0, 0), center, self.cell_size // 3, 2)

        # Draw main text (identifier)
        text_surface = self.font.render(text, True, (255, 255, 255))
        text_rect = text_surface.get_rect(center=center)
        self.screen.blit(text_surface, text_rect)

        # Draw info text above the element
        if info_text:
            info_surface = self.small_font.render(info_text, True, (0, 0, 0))
            info_rect = info_surface.get_rect(
                midbottom=(center[0], center[1] - self.cell_size // 3 - 5)
            )

            # Draw white background for text
            bg_rect = info_rect.inflate(10, 6)
            pygame.draw.rect(self.screen, (255, 255, 255), bg_rect)
            pygame.draw.rect(self.screen, (200, 200, 200), bg_rect, 1)

            self.screen.blit(info_surface, info_rect)

    def draw_status_bar(self, env, trucks, bins):
        """Draw status bar with simulation information including day"""
        status_rect = pygame.Rect(0, self.window_size, self.window_size, self.status_height)
        pygame.draw.rect(self.screen, self.COLORS['status_bg'], status_rect)

        # Get current day directly from environment
        current_day = env.current_day

        # Create time string
        hour = int(env.current_time)
        minutes = int((env.current_time % 1) * 60)
        time_str = f"{hour:02d}:{minutes:02d}"

        total_collections = sum(truck.total_collections for truck in trucks)
        total_waste = sum(bin_agent.total_waste_generated for bin_agent in bins)
        traffic_status = "RUSH HOUR" if (7 <= env.current_time <= 9 or 17 <= env.current_time <= 19) else "Normal"

        status_texts = [
            f"Day: {current_day}/7",
            f"Time: {time_str}",
            f"Traffic: {traffic_status}",
            f"Collections: {total_collections}",
            f"Waste: {total_waste:.1f}"
        ]

        x_offset = 10
        for text in status_texts:
            text_surface = self.small_font.render(text, True, (255, 255, 255))
            self.screen.blit(text_surface, (x_offset, self.window_size + 12))
            x_offset += text_surface.get_width() + 20

    def update_display(self, env, trucks, bins):
        """Update the display with current simulation state"""
        self.draw_grid()

        # Draw depot
        self.draw_element(env.depot["position"], self.COLORS['depot'], "D", "Depot")

        # Draw fuel stations
        for station in env.fuel_stations:
            self.draw_element(station["position"], self.COLORS['fuel'], "F", "Fuel")

        # Draw bins with consistent color
        for bin_agent in bins:
            fill_level = f"{(bin_agent.current_level / bin_agent.capacity) * 100:.0f}%"
            self.draw_element(bin_agent.position, self.COLORS['bin'], "B", fill_level)

        # Draw trucks last (so they appear on top)
        for i, truck in enumerate(trucks):
            status = f"F:{truck.fuel_level:.0f} W:{truck.current_waste:.0f}"
            color = self.COLORS['truck_busy'] if truck.busy else self.COLORS['truck_idle']
            self.draw_element(truck.position, color, f"T{i + 1}", status)

        self.draw_status_bar(env, trucks, bins)
        pygame.display.flip()

    def close(self):
        """Close the pygame window and quit pygame"""
        try:
            pygame.display.quit()
            pygame.quit()
        except Exception as e:
            print(f"Error while closing pygame: {e}")