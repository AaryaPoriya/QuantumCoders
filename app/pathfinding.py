
import heapq

class AStar:
    def __init__(self, grid):
        self.grid = grid
        self.width = len(grid[0])
        self.height = len(grid)

    def find_path(self, start, end):
        # Internal representation is (row, col) which is (y, x)
        # The input `start` and `end` are (x, y)
        start_node = (int(start[1]), int(start[0]))
        end_node = (int(end[1]), int(end[0]))

        if not (0 <= start_node[0] < self.height and 0 <= start_node[1] < self.width):
            return None # Start node is out of bounds
        if not (0 <= end_node[0] < self.height and 0 <= end_node[1] < self.width):
            return None # End node is out of bounds
        if self.grid[start_node[0]][start_node[1]] == 1:
            return None # Start node is on an obstacle
        
        # Allow the end node to be an obstacle. The path will lead to the closest walkable node.
        if self.grid[end_node[0]][end_node[1]] == 1:
            self.grid[end_node[0]][end_node[1]] = 0 # Temporarily mark as walkable to find a path to it

        open_set = []
        heapq.heappush(open_set, (0, start_node))
        came_from = {}
        g_score = { (r,c): float('inf') for r in range(self.height) for c in range(self.width) }
        g_score[start_node] = 0
        f_score = { (r,c): float('inf') for r in range(self.height) for c in range(self.width) }
        f_score[start_node] = self.heuristic(start_node, end_node)

        while open_set:
            _, current = heapq.heappop(open_set)

            if current == end_node:
                self.grid[end_node[0]][end_node[1]] = 1 # Restore obstacle if it was one
                return self.reconstruct_path(came_from, current)

            for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                neighbor = (current[0] + dr, current[1] + dc)

                if 0 <= neighbor[0] < self.height and 0 <= neighbor[1] < self.width:
                    if self.grid[neighbor[0]][neighbor[1]] == 1:
                        continue
                    
                    tentative_g_score = g_score[current] + self.heuristic(current, neighbor)

                    if tentative_g_score < g_score[neighbor]:
                        came_from[neighbor] = current
                        g_score[neighbor] = tentative_g_score
                        f_score[neighbor] = tentative_g_score + self.heuristic(neighbor, end_node)
                        if neighbor not in [i[1] for i in open_set]:
                            heapq.heappush(open_set, (f_score[neighbor], neighbor))
        
        self.grid[end_node[0]][end_node[1]] = 1 # Restore obstacle if it was one
        return None

    def heuristic(self, a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def reconstruct_path(self, came_from, current):
        path = []
        while current in came_from:
            path.append(current)
            current = came_from[current]
        path.append(current)
        return path[::-1]

def create_grid_from_db(sections, max_x, max_y, resolution=1):
    grid_width = int(max_x * resolution) + 1
    grid_height = int(max_y * resolution) + 1
    grid = [[0 for _ in range(grid_width)] for _ in range(grid_height)]

    for section in sections:
        x1, y1 = int(section['x1'] * resolution), int(section['y1'] * resolution)
        x2, y2 = int(section['x2'] * resolution), int(section['y2'] * resolution)

        for r in range(min(y1, y2), max(y1, y2) + 1):
            for c in range(min(x1, x2), max(x1, x2) + 1):
                if 0 <= r < grid_height and 0 <= c < grid_width:
                    grid[r][c] = 1 # Mark as obstacle
    
    return grid 