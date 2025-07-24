
import heapq
import collections

def astar(grid, start, end):
    height, width = len(grid), len(grid[0])
    
    # Check if start or end are out of bounds
    if not (0 <= start[0] < height and 0 <= start[1] < width): return None
    if not (0 <= end[0] < height and 0 <= end[1] < width): return None

    # If start or end are obstacles, find the nearest walkable node
    if grid[start[0]][start[1]] == 1:
        start = find_nearest_walkable(grid, start)
        if start is None: return None # No path if start is trapped
            
    if grid[end[0]][end[1]] == 1:
        end = find_nearest_walkable(grid, end)
        if end is None: return None # No path if end is trapped

    open_set = [(0, start)]
    came_from = {}
    
    g_score = { (r, c): float('inf') for r in range(height) for c in range(width) }
    g_score[start] = 0
    
    f_score = { (r, c): float('inf') for r in range(height) for c in range(width) }
    f_score[start] = heuristic(start, end)

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == end:
            return reconstruct_path(came_from, current)

        # Use 4-directional movement for grid paths
        for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            neighbor = (current[0] + dr, current[1] + dc)

            if not (0 <= neighbor[0] < height and 0 <= neighbor[1] < width) or grid[neighbor[0]][neighbor[1]] == 1:
                continue
            
            # Using cost of 1 for adjacent grid cells
            tentative_g_score = g_score[current] + 1

            if tentative_g_score < g_score[neighbor]:
                came_from[neighbor] = current  # <-- THE CRITICAL BUG FIX IS HERE
                g_score[neighbor] = tentative_g_score
                f_score[neighbor] = tentative_g_score + heuristic(neighbor, end)
                heapq.heappush(open_set, (f_score[neighbor], neighbor))
                
    return None # Path not found

def find_nearest_walkable(grid, node):
    q = collections.deque([node])
    visited = {node}
    
    while q:
        y, x = q.popleft()
        
        if grid[y][x] == 0:
            return (y, x)
            
        # Use 4-directional search
        for dy, dx in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            ny, nx = y + dy, x + dx
            
            if (0 <= ny < len(grid) and 0 <= nx < len(grid[0])) and (ny, nx) not in visited:
                visited.add((ny, nx))
                q.append((ny, nx))
                
    return None

def heuristic(a, b):
    # Manhattan distance for 4-directional movement
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def reconstruct_path(came_from, current):
    path = [current]
    while current in came_from:
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
                    grid[r][c] = 1
    
    return grid 