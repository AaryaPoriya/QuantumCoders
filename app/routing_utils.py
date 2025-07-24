
import math

def get_direction_change(p1, p2, p3):
    angle1 = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    angle2 = math.atan2(p3[1] - p2[1], p3[0] - p2[0])
    
    angle_diff = math.degrees(angle2 - angle1)
    
    if angle_diff > 180:
        angle_diff -= 360
    if angle_diff < -180:
        angle_diff += 360

    if -45 <= angle_diff <= 45:
        return "Proceed straight"
    elif angle_diff > 45:
        return "Turn left"
    else: # angle_diff < -45
        return "Turn right"

def enrich_path(path, product_locations):
    if not path or len(path) < 2:
        return path

    enriched_path = []
    
    # Initialize path points
    for point in path:
        point['section_id'] = None
        point['instruction'] = None
        enriched_path.append(point)

    # Determine instructions at turning points
    if len(enriched_path) > 2:
        for i in range(1, len(enriched_path) - 1):
            p1 = (enriched_path[i-1]['x'], enriched_path[i-1]['y'])
            p2 = (enriched_path[i]['x'], enriched_path[i]['y'])
            p3 = (enriched_path[i+1]['x'], enriched_path[i+1]['y'])
            
            instruction = get_direction_change(p1, p2, p3)
            if instruction != "Proceed straight":
                 enriched_path[i]['instruction'] = instruction
    
    # Add an arrival instruction and section_id for each destination
    for product_id, loc in product_locations.items():
        min_dist = float('inf')
        arrival_index = -1
        product_x, product_y = loc['x_coord'], loc['y_coord']

        for i, point in enumerate(enriched_path):
            dist = ((point['x'] - product_x)**2 + (point['y'] - product_y)**2)**0.5
            if dist < min_dist:
                min_dist = dist
                arrival_index = i

        if arrival_index != -1:
            enriched_path[arrival_index]['instruction'] = "You have arrived at your product"
            enriched_path[arrival_index]['section_id'] = loc['section_id']

    return enriched_path 