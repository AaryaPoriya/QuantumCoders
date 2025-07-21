
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

def enrich_path(path, product_locations, sections):
    if not path or len(path) < 2:
        return path

    enriched_path = []
    
    # Associate each point with a section
    for i in range(len(path)):
        point = path[i]
        section_id = get_section_for_point(point, sections)
        point['section_id'] = section_id
        point['instruction'] = None # Initialize instruction
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
    
    # Add an arrival instruction for each destination
    for product_id, loc in product_locations.items():
        # Find the point in the path closest to this product's location
        # This is a simplification; assumes the path endpoint for a segment is the arrival point
        min_dist = float('inf')
        arrival_index = -1
        for i, point in enumerate(enriched_path):
            dist = ((point['x'] - loc['x_coord'])**2 + (point['y'] - loc['y_coord'])**2)**0.5
            if dist < min_dist:
                min_dist = dist
                arrival_index = i

        if arrival_index != -1:
            enriched_path[arrival_index]['instruction'] = f"You have arrived at your product"

    return enriched_path

def get_section_for_point(point, sections):
    px, py = point['x'], point['y']
    for section in sections:
        is_inside = (section['x1'] <= px <= section['x2'] or section['x2'] <= px <= section['x1']) and \
                    (section['y1'] <= py <= section['y2'] or section['y2'] <= py <= section['y1'])
        if is_inside:
            return section['section_id']
    return None 