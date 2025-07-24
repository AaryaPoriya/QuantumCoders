
import heapq
import collections

def astar(grid, start, end):
    height = len(grid)
    width = len(grid[0])
    
    # Check if start or end are out of bounds
    if not (0 <= start[0] < height and 0 <= start[1] < width): return None
    if not (0 <= end[0] < height and 0 <= end[1] < width): return None

    # If start or end are obstacles, find the nearest walkable node
    if grid[start[0]][start[1]] == 1:
        start = find_nearest_walkable(grid, start)
        if start is None: return None
            
    if grid[end[0]][end[1]] == 1:
        end = find_nearest_walkable(grid, end)
        if end is None: return None

    open_set = []
    heapq.heappush(open_set, (0, start))
    
    came_from = {}
    g_score = { (r,c): float('inf') for r in range(height) for c in range(width) }
    g_score[start] = 0
    
    f_score = { (r,c): float('inf') for r in range(height) for c in range(width) }
    f_score[start] = heuristic(start, end)

    while open_set:
        _, current = heapq.heappop(open_set)

        if current == end:
            return reconstruct_path(came_from, current)

        for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]:
            neighbor = (current[0] + dr, current[1] + dc)

            if not (0 <= neighbor[0] < height and 0 <= neighbor[1] < width) or grid[neighbor[0]][neighbor[1]] == 1:
                continue
            
            tentative_g_score = g_score[current] + heuristic(current, neighbor)

            if tentative_g_score < g_score[neighbor]:
                came_from[neighbor] = neighbor
                g_score[neighbor] = tentative_g_score
                f_score[neighbor] = tentative_g_score + heuristic(neighbor, end)
                heapq.heappush(open_set, (f_score[neighbor], neighbor))
                
    return None

def find_nearest_walkable(grid, node):
    height = len(grid)
    width = len(grid[0])
    
    q = collections.deque([(node, [node])])
    visited = {node}
    
    while q:
        current_node, path = q.popleft()
        
        if grid[current_node[0]][current_node[1]] == 0:
            return current_node
            
        for dr, dc in [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]:
            neighbor = (current_node[0] + dr, current_node[1] + dc)
            
            if (0 <= neighbor[0] < height and 0 <= neighbor[1] < width) and neighbor not in visited:
                visited.add(neighbor)
                new_path = list(path)
                new_path.append(neighbor)
                q.append((neighbor, new_path))
                
    return None

def heuristic(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

def reconstruct_path(came_from, current):
    path = [current]
    while current in came_from and came_from[current] != current:
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