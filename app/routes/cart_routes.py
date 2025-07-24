from flask import Blueprint, request, jsonify
from pydantic import ValidationError
from app.models import (
    ShortestPathRequest, ShortestPathResponse, PathSegment
)
from app.db import execute_query
from app.auth import jwt_required, get_current_user_id
from app.utils import serialize_row
from app.pathfinding import astar, create_grid_from_db
from app.routing_utils import process_path
import logging

logger = logging.getLogger(__name__)
bp = Blueprint('cart', __name__, url_prefix='/cart')

@bp.route('/shortest_path', methods=['POST'])
@jwt_required
def get_shortest_path_route():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({"detail": "Authentication required."}), 401

    try:
        data = ShortestPathRequest(**request.json)
    except ValidationError as e:
        return jsonify({"detail": e.errors()}), 400

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # 1. Get user's cart location
            cur.execute("""
                SELECT cl.x_coord, cl.y_coord 
                FROM public.total_carts tc
                JOIN public.cart_locations cl ON tc.cart_id = cl.cart_id
                WHERE tc.user_id = %s ORDER BY cl.updated_at DESC LIMIT 1;
            """, (user_id,))
            start_pos_raw = cur.fetchone()
            if not start_pos_raw:
                return jsonify({"detail": "Could not find a connected cart with a location."}), 404
            start_pos = (float(start_pos_raw[0]), float(start_pos_raw[1]))

            # 2. Fetch layout and product locations
            cur.execute("SELECT section_id, x1, y1, x2, y2 FROM public.store_sections;")
            sections = [serialize_row(row, cur.description) for row in cur.fetchall()]
            
            product_ids = [dest.product_id for dest in data.destinations]
            cur.execute("SELECT product_id, x_coord, y_coord, section_id FROM public.product_locations WHERE product_id = ANY(%s);", (product_ids,))
            product_locs = {row[0]: serialize_row(row, cur.description) for row in cur.fetchall()}

            # 3. Create grid
            max_x = max(s['x2'] for s in sections) if sections else 100
            max_y = max(s['y2'] for s in sections) if sections else 100
            resolution = 10
            grid = create_grid_from_db(sections, max_x, max_y, resolution)
            
            # Add hardcoded restricted zone
            for r in range(int(0.725 * resolution), int(1.250 * resolution) + 1):
                for c in range(int(0.750 * resolution), int(3.250 * resolution) + 1):
                    if 0 <= r < len(grid) and 0 <= c < len(grid[0]):
                        grid[r][c] = 1

            # 4. Calculate full path
            full_path = []
            current_pos = start_pos
            
            destinations_in_order = sorted(
                [p for p in product_ids if p in product_locs],
                key=lambda p_id: ((product_locs[p_id]['x_coord'] - current_pos[0])**2 + (product_locs[p_id]['y_coord'] - current_pos[1])**2)**0.5
            )

            for p_id in destinations_in_order:
                dest_pos = (product_locs[p_id]['x_coord'], product_locs[p_id]['y_coord'])
                start_scaled = (int(current_pos[0] * resolution), int(current_pos[1] * resolution))
                end_scaled = (int(dest_pos[0] * resolution), int(dest_pos[1] * resolution))
                
                segment = astar(grid, start_scaled, end_scaled)
                if segment:
                    full_path.extend(segment if not full_path else segment[1:])
                    last_point_scaled = segment[-1]
                    current_pos = (last_point_scaled[1] / resolution, last_point_scaled[0] / resolution)
                else:
                    logger.warning(f"Could not find path from {current_pos} to {dest_pos}")

            if not full_path:
                return jsonify({"detail": "Could not calculate a valid path."}), 422
            
            # 5. Process and return path
            processed_path = process_path(full_path, product_locs)
            response_path = [PathSegment(**p) for p in processed_path if p['instruction'] is not None]
            
        return jsonify(ShortestPathResponse(path=response_path).dict()), 200

    except Exception as e:
        logger.error(f"Error in shortest_path: {e}")
        return jsonify({"detail": "Internal server error"}), 500
    finally:
        if conn and not conn.closed:
            close_conn(conn) 
