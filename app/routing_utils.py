
import math

def get_instruction(p1, p2, p3):
    angle1 = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    angle2 = math.atan2(p3[1] - p2[1], p3[0] - p2[0])
    angle_diff = math.degrees(angle2 - angle1)
    
    angle_diff = (angle_diff + 180) % 360 - 180

    if -45 <= angle_diff <= 45:
        return None
    elif angle_diff > 45:
        return "Turn left"
    else:
        return "Turn right"

def process_path(path_coords, product_locations):
    if not path_coords:
        return []

    enriched_path = [{'x': p[1], 'y': p[0], 'instruction': None, 'section_id': None} for p in path_coords]

    # Add turning instructions
    if len(enriched_path) > 2:
        for i in range(1, len(enriched_path) - 1):
            p1 = (enriched_path[i-1]['x'], enriched_path[i-1]['y'])
            p2 = (enriched_path[i]['x'], enriched_path[i]['y'])
            p3 = (enriched_path[i+1]['x'], enriched_path[i+1]['y'])
            enriched_path[i]['instruction'] = get_instruction(p1, p2, p3)

    # Add arrival instructions
    for prod_id, loc in product_locations.items():
        min_dist = float('inf')
        arrival_idx = -1
        for i, point in enumerate(enriched_path):
            dist = ((point['x'] - loc['x_coord'])**2 + (point['y'] - loc['y_coord'])**2)**0.5
            if dist < min_dist:
                min_dist = dist
                arrival_idx = i
        
        if arrival_idx != -1:
            enriched_path[arrival_idx]['instruction'] = "You have arrived at your product"
            enriched_path[arrival_idx]['section_id'] = loc['section_id']

    return enriched_path 