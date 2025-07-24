from flask import Blueprint, request, jsonify
from pydantic import ValidationError
from app.models import (
    ConnectCartRequest, CartConnectionResponse, CartViewResponse, CartItem as CartItemModel, Product as ProductModel,
    CartLocation as CartLocationModel, ProductLocation as ProductLocationModel, StoreSection as StoreSectionModel,
    ShortestPathRequest, ShortestPathResponse, PathSegment,
    Esp32CartUpdateRequest, CartItemAddRequest, CartItemRemoveRequest, 
    ErrorResponse, MessageResponse
)
from app.db import execute_query
from app.auth import jwt_required, get_current_user_id
from app.utils import handle_pydantic_error, serialize_row, serialize_rows
import logging
import psycopg2 # For specific error handling
import math
from heapq import heappush, heappop

logger = logging.getLogger(__name__)
bp = Blueprint('cart', __name__, url_prefix='/cart')

# ----------- CONFIG & PATHFINDING GLOBALS -----------
GRID_RES = 0.05
CENTERLINE_SET = set() # Global set for walkable points

# ----------- NEW PATHFINDING IMPLEMENTATION -----------

def build_centerline_graph(sections):
    """Builds a robust, connected graph of all aisle centerlines."""
    global CENTERLINE_SET
    step = GRID_RES
    centerline_points = set()

    h_aisles = {} # {y_coord: [min_x, max_x]}
    v_aisles = {} # {x_coord: [min_y, max_y]}

    # First, identify all horizontal and vertical aisle centerlines
    for sec in sections:
        x1, x2 = min(sec['x1'], sec['x2']), max(sec['x1'], sec['x2'])
        y1, y2 = min(sec['y1'], sec['y2']), max(sec['y1'], sec['y2'])
        
        if (x2 - x1) > (y2 - y1): # Horizontal aisle
            center_y = round((y1 + y2) / 2, 2)
            if center_y not in h_aisles: h_aisles[center_y] = [x1, x2]
            else:
                h_aisles[center_y][0] = min(h_aisles[center_y][0], x1)
                h_aisles[center_y][1] = max(h_aisles[center_y][1], x2)
        else: # Vertical aisle
            center_x = round((x1 + x2) / 2, 2)
            if center_x not in v_aisles: v_aisles[center_x] = [y1, y2]
            else:
                v_aisles[center_x][0] = min(v_aisles[center_x][0], y1)
                v_aisles[center_x][1] = max(v_aisles[center_x][1], y2)

    # Add all points along the identified aisle centerlines
    for y, x_range in h_aisles.items():
        x = x_range[0]
        while x <= x_range[1]:
            centerline_points.add((round(x, 2), y))
            x += step

    for x, y_range in v_aisles.items():
        y = y_range[0]
        while y <= y_range[1]:
            centerline_points.add((x, round(y, 2)))
            y += step
            
    # Crucially, add the intersection points of every h-aisle with every v-aisle
    for y in h_aisles:
        for x in v_aisles:
            centerline_points.add((x, y))

    CENTERLINE_SET = centerline_points

def find_nearest_centerline_node(coords):
    """Finds the closest point in the centerline_set to the given coordinates."""
    if not CENTERLINE_SET:
        return None
    return min(CENTERLINE_SET, key=lambda p: math.dist(coords, p))

def is_walkable(x, y):
    """Checks if a point is on a pre-calculated centerline."""
    return (round(x, 2), round(y, 2)) in CENTERLINE_SET

def heuristic(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def astar(start_node, goal_node):
    """
    Finds the shortest path between two nodes that are already on the centerline.
    """
    if not start_node or not goal_node:
        return []

    open_set = []
    heappush(open_set, (0, start_node))
    came_from = {}
    g_score = {start_node: 0}

    while open_set:
        _, current = heappop(open_set)

        if current == goal_node:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return path[::-1]

        cx, cy = current
        for dx, dy in [(GRID_RES, 0), (-GRID_RES, 0), (0, GRID_RES), (0, -GRID_RES)]:
            nx, ny = round(cx + dx, 2), round(cy + dy, 2)
            
            if not is_walkable(nx, ny):
                continue
            
            tentative_g = g_score.get(current, float('inf')) + GRID_RES
            
            if tentative_g < g_score.get((nx, ny), float('inf')):
                came_from[(nx, ny)] = current
                g_score[(nx, ny)] = tentative_g
                f = tentative_g + heuristic((nx, ny), goal_node)
                heappush(open_set, (f, (nx, ny)))
    return []

def snap_to_section_center(section, prod_x, prod_y):
    """
    Snap a product's coordinates to the centerline of its section.
    If the section is wider than tall (horizontal aisle), snap Y to centerline.
    If the section is taller than wide (vertical aisle), snap X to centerline.
    """
    x1, x2 = min(section['x1'], section['x2']), max(section['x1'], section['x2'])
    y1, y2 = min(section['y1'], section['y2']), max(section['y1'], section['y2'])

    width = x2 - x1
    height = y2 - y1

    if width >= height:
        # horizontal aisle: fix Y to centerline
        center_y = round((y1 + y2) / 2, 2)
        return (round(prod_x, 2), center_y)
    else:
        # vertical aisle: fix X to centerline
        center_x = round((x1 + x2) / 2, 2)
        return (center_x, round(prod_y, 2))

# API 13: Connect Cart
@bp.route('/connect', methods=['POST'])
@jwt_required
def connect_cart_route():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401

    try:
        data = ConnectCartRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # Check if the user is already connected to any cart
            cur.execute("SELECT cart_id FROM public.total_carts WHERE user_id = %s;", (user_id,))
            existing_cart_row = cur.fetchone()
            if existing_cart_row:
                if existing_cart_row[0] == data.cart_id:
                    return jsonify(CartConnectionResponse(cart_id=data.cart_id, user_id=user_id, message="You are already connected to this cart.").dict()), 200
                else:
                    return jsonify(ErrorResponse(detail=f'You are already connected to cart {existing_cart_row[0]}. Please disconnect first.').dict()), 409

            # Check the status of the requested cart
            cur.execute("SELECT user_id FROM public.total_carts WHERE cart_id = %s;", (data.cart_id,))
            cart_row = cur.fetchone()

            if not cart_row:
                return jsonify(ErrorResponse(detail=f'Cart with ID {data.cart_id} does not exist.').dict()), 404
            
            cart_user_id = cart_row[0]
            if cart_user_id is not None:
                return jsonify(ErrorResponse(detail=f'Cart {data.cart_id} is already in use by another user.').dict()), 409

            # If we reach here, the cart exists and is available. Assign it to the user.
            update_query = "UPDATE public.total_carts SET user_id = %s WHERE cart_id = %s;"
            cur.execute(update_query, (user_id, data.cart_id))
            conn.commit()
        
        return jsonify(CartConnectionResponse(cart_id=data.cart_id, user_id=user_id, message="Cart connected successfully.").dict()), 200

    except psycopg2.Error as db_err:
        if conn: conn.rollback()
        logger.error(f"Database error connecting cart for user {user_id}: {db_err}")
        return jsonify(ErrorResponse(detail=f'Database error: {str(db_err)}').dict()), 500
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Error connecting cart for user {user_id}: {e}")
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500
    finally:
        if conn and not conn.closed:
             close_conn(conn)

# API 14: View Cart
@bp.route('/view', methods=['GET'])
@jwt_required
def view_cart_route():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401

    query = """
    WITH user_cart AS (
        SELECT cart_id, cart_weight FROM public.total_carts WHERE user_id = %s LIMIT 1
    )
    SELECT 
        uc.cart_id,
        uc.cart_weight,
        (
            SELECT json_agg(
                json_build_object(
                    'cart_items_id', ci.cart_items_id,
                    'cart_id', ci.cart_id,
                    'product_id', ci.product_id,
                    'quantity', ci.quantity,
                    'product', json_build_object(
                        'product_id', p.product_id,
                        'product_name', p.product_name,
                        'price', p.price,
                        'discounted_price', p.discounted_price,
                        'barcode', p.barcode,
                        'weight', p.weight,
                        'expiry', p.expiry,
                        'category_id', p.category_id,
                        'offer_name', p.offer_name
                    )
                )
            )
            FROM public.cart_items ci
            JOIN public.product p ON ci.product_id = p.product_id
            WHERE ci.cart_id = uc.cart_id
        ) as items
    FROM user_cart uc;
    """
    
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query, (user_id,))
            row = cur.fetchone()
            
            if not row or not row[0]:
                close_conn(conn)
                return jsonify(ErrorResponse(detail='No active cart found for user.').dict()), 404
            
            cart_data = serialize_row(row, cur.description)
            items_list = cart_data.get('items') or []
            
            # Pydantic models will handle the float conversion for weight
            response_data = CartViewResponse(
                cart_id=cart_data['cart_id'],
                items=[CartItemModel(**item) for item in items_list],
                total_weight=cart_data.get('cart_weight')
            )

        close_conn(conn)
        return jsonify(response_data.dict()), 200
    except Exception as e:
        logger.error(f"Error viewing cart for user {user_id}: {e}")
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

# API 15: Get Cart's Current Location
@bp.route('/<int:cart_id>/location', methods=['GET'])
@jwt_required 
def get_cart_location_route(cart_id):
    user_id = get_current_user_id()
    check_owner_query = "SELECT user_id FROM public.total_carts WHERE cart_id = %s AND user_id = %s;"
    owner_row = execute_query(check_owner_query, (cart_id, user_id), fetchone=True)
    if not owner_row:
        return jsonify(ErrorResponse(detail=f'Cart {cart_id} not found or does not belong to user.').dict()), 403

    query = """
    SELECT cart_id, x_coord, y_coord, section_id, updated_at 
    FROM public.cart_locations 
    WHERE cart_id = %s 
    ORDER BY updated_at DESC LIMIT 1;
    """
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        cart_loc_dict = None
        with conn.cursor() as cur:
            cur.execute(query, (cart_id,))
            row = cur.fetchone()
            if not row:
                close_conn(conn)
                return jsonify(ErrorResponse(detail=f'Location not found for cart {cart_id}.').dict()), 404
            cart_loc_dict = serialize_row(row, cur.description)
        close_conn(conn)

        if cart_loc_dict:
            return jsonify(CartLocationModel(**cart_loc_dict).dict()), 200
        else:
             return jsonify(ErrorResponse(detail=f'Location not found for cart {cart_id}.').dict()), 404
    except Exception as e:
        logger.error(f"Error fetching location for cart {cart_id}: {e}")
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

# API 17: Get Product Locations
@bp.route('/product_locations', methods=['GET'])
@jwt_required
def get_product_locations_route():
    product_ids_str = request.args.get('product_ids')
    if not product_ids_str:
        return jsonify(ErrorResponse(detail='product_ids parameter is required (comma-separated).').dict()), 400
    try:
        product_ids = [int(pid.strip()) for pid in product_ids_str.split(',')]
        if not product_ids:
             return jsonify(ErrorResponse(detail='No valid product_ids provided.').dict()), 400
    except ValueError:
        return jsonify(ErrorResponse(detail='Invalid product_ids format. Must be comma-separated integers.').dict()), 400

    query = """
    SELECT pl.product_id, pl.section_id, pl.aisle_num, pl.shelf_num, pl.x_coord, pl.y_coord,
           ss.section_name, ss.x1, ss.y1, ss.x2, ss.y2, ss.floor_level
    FROM public.product_locations pl
    JOIN public.store_sections ss ON pl.section_id = ss.section_id
    WHERE pl.product_id IN %s;
    """
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        locations_data = []
        with conn.cursor() as cur:
            cur.execute(query, (tuple(product_ids),))
            rows = cur.fetchall()
            if rows:
                for row_data in rows:
                    serialized_loc = serialize_row(row_data, cur.description)
                    section_data = StoreSectionModel(
                        section_id=serialized_loc['section_id'],
                        section_name=serialized_loc['section_name'],
                        x1=serialized_loc['x1'], y1=serialized_loc['y1'],
                        x2=serialized_loc['x2'], y2=serialized_loc['y2'],
                        floor_level=serialized_loc['floor_level']
                    )
                    loc_obj = ProductLocationModel(
                        product_id=serialized_loc['product_id'],
                        section_id=serialized_loc['section_id'],
                        aisle_num=serialized_loc['aisle_num'],
                        shelf_num=serialized_loc['shelf_num'],
                        x_coord=serialized_loc['x_coord'],
                        y_coord=serialized_loc['y_coord'],
                        section=section_data
                    )
                    locations_data.append(loc_obj)
        close_conn(conn)
        return jsonify([loc.dict() for loc in locations_data]), 200
    except Exception as e:
        logger.error(f"Error fetching product locations for ids {product_ids}: {e}")
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

# API 18: Get Shortest Path
@bp.route('/shortest_path', methods=['POST'])
@jwt_required
def get_shortest_path_route():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401
    
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # Step 1: Build the centerline graph from store section data
            cur.execute("SELECT x1, y1, x2, y2 FROM public.store_sections;")
            sections_raw = cur.fetchall()
            sections = [{'x1': float(r[0]), 'y1': float(r[1]), 'x2': float(r[2]), 'y2': float(r[3])} for r in sections_raw]
            build_centerline_graph(sections)

            # Step 2: Get user's active cart location and snap it to the centerline
            cur.execute("""
                SELECT cl.x_coord, cl.y_coord FROM public.total_carts tc
                JOIN public.cart_locations cl ON tc.cart_id = cl.cart_id
                WHERE tc.user_id = %s ORDER BY cl.updated_at DESC LIMIT 1;
            """, (user_id,))
            cart_loc_row = cur.fetchone()
            if not cart_loc_row:
                return jsonify({"error": "No active cart location found for user."}), 404
            
            original_start = (float(cart_loc_row[0]), float(cart_loc_row[1]))
            start = find_nearest_centerline_node(original_start)

            # Force fallback if no snap found
            if not start and CENTERLINE_SET:
                start = min(CENTERLINE_SET, key=lambda p: math.dist(original_start, p))
            
            if not start:
                logger.error("Could not snap cart's start location to any centerline node.")
                return jsonify({"error": "Could not determine a valid starting position on the route."}), 500

            # Step 3: Get product destinations
            body = request.get_json()
            product_ids = [d.get('product_id') for d in body.get('destinations', [])]
            if not product_ids:
                return jsonify({"error": "No destinations provided."}), 400

            cur.execute("""
                SELECT product_id, x_coord, y_coord, section_id FROM public.product_locations
                WHERE product_id = ANY(%s)
            """, (product_ids,))
            prod_locs_raw = cur.fetchall()
            prod_locs = {r[0]: {'x_coord': float(r[1]), 'y_coord': float(r[2]), 'section_id': r[3]} for r in prod_locs_raw}
            
            # Step 4: Order targets by nearest and calculate path
            targets = [(pid, (prod_locs[pid]['x_coord'], prod_locs[pid]['y_coord']), prod_locs[pid]['section_id']) for pid in product_ids if pid in prod_locs]
            
            ordered_targets = []
            current_pos_for_sort = start
            while targets:
                next_target = min(targets, key=lambda t: math.dist(current_pos_for_sort, t[1]))
                ordered_targets.append(next_target)
                targets.remove(next_target)
                current_pos_for_sort = next_target[1]

            path_segments = []
            # Initialize the start of the first segment with the SNAPPED cart location.
            current_path_start = start 
            for pid, coords, sec_id in ordered_targets:
                # Fetch section geometry for robust snapping
                cur.execute("SELECT x1,y1,x2,y2 FROM public.store_sections WHERE section_id=%s", (sec_id,))
                sec_row = cur.fetchone()
                if not sec_row:
                    logger.warning(f"Could not find section geometry for product {pid} in section {sec_id}")
                    continue
                section_geom = {'x1':float(sec_row[0]), 'y1':float(sec_row[1]), 'x2':float(sec_row[2]), 'y2':float(sec_row[3])}

                # Snap the goal to its own section's centerline, then to the global graph.
                section_snap = snap_to_section_center(section_geom, coords[0], coords[1])
                snapped_goal = find_nearest_centerline_node(section_snap)

                if not snapped_goal:
                    logger.warning(f"Could not snap goal for product {pid}")
                    continue

                # The start point is already guaranteed to be on the centerline.
                segment = astar(current_path_start, snapped_goal)
                if not segment:
                    logger.warning(f"Could not find path from {current_path_start} to {snapped_goal} for product {pid}")
                    continue

                path_segments.append({
                    "product_id": pid,
                    "section_id": sec_id,
                    "destination": {"x": coords[0], "y": coords[1]},
                    "path_length": len(segment),
                    "path": [{"x": p[0], "y": p[1]} for p in segment],
                    "last_instruction": f"You have arrived at section {sec_id}"
                })
                # CRITICAL FIX: The start of the next segment is the snapped goal of this one.
                current_path_start = snapped_goal

    finally:
        if conn and not conn.closed:
            close_conn(conn)

    return jsonify({
        "start": {"x": start[0], "y": start[1]},
        "segments": path_segments
    })

# API 20: Add/Update Item in Cart (from ESP32)
@bp.route('/esp32/update_item', methods=['POST'])
def update_cart_item_esp32_route():
    try:
        data = Esp32CartUpdateRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # Check if the product exists
            cur.execute("SELECT weight FROM public.product WHERE product_id = %s;", (data.product_id,))
            product_row = cur.fetchone()
            if not product_row:
                conn.rollback()
                return jsonify(ErrorResponse(detail=f"Product with ID {data.product_id} not found.").dict()), 404
            
            base_product_weight = product_row[0]
            if base_product_weight is None or base_product_weight == 0:
                conn.rollback() # No need to proceed if weight is not defined
                return jsonify(ErrorResponse(detail=f"Product with ID {data.product_id} has no defined weight.").dict()), 400

            # Determine quantity from total weight measured by ESP32
            # This logic assumes the weight passed is the total for that product type
            quantity = round(data.weight / base_product_weight)

            if quantity > 0:
                # Upsert: Update quantity if item exists, else insert
                upsert_query = """
                INSERT INTO public.cart_items (cart_id, product_id, quantity)
                VALUES (%s, %s, %s)
                ON CONFLICT (cart_id, product_id)
                DO UPDATE SET quantity = EXCLUDED.quantity;
                """
                cur.execute(upsert_query, (data.cart_id, data.product_id, quantity))
            else:
                # If quantity is 0, remove the item from the cart
                delete_query = "DELETE FROM public.cart_items WHERE cart_id = %s AND product_id = %s;"
                cur.execute(delete_query, (data.cart_id, data.product_id))

            # After updating cart items, update the total weight in the total_carts table
            # This requires summing up all item weights in the cart
            update_weight_query = """
            UPDATE public.total_carts tc
            SET cart_weight = (
                SELECT SUM(p.weight * ci.quantity)
                FROM public.cart_items ci
                JOIN public.product p ON ci.product_id = p.product_id
                WHERE ci.cart_id = tc.cart_id
            )
            WHERE tc.cart_id = %s;
            """
            cur.execute(update_weight_query, (data.cart_id,))
            conn.commit()

        close_conn(conn)
        return jsonify(MessageResponse(message=f"Cart {data.cart_id} updated for product {data.product_id} with quantity {quantity}.").dict()), 200

    except psycopg2.Error as db_err:
        if conn: conn.rollback()
        logger.error(f"DB error in /esp32/update_item: {db_err}")
        return jsonify(ErrorResponse(detail=f"Database error: {str(db_err)}").dict()), 500
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Error in /esp32/update_item: {e}")
        return jsonify(ErrorResponse(detail="Internal server error.").dict()), 500
    finally:
        if conn and not conn.closed:
            close_conn(conn)

@bp.route('/item/add', methods=['POST'])
@jwt_required
def add_product_to_cart_route():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401
        
    try:
        data = CartItemAddRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # Get the user's cart_id
            cur.execute("SELECT cart_id FROM public.total_carts WHERE user_id = %s LIMIT 1;", (user_id,))
            cart_row = cur.fetchone()
            if not cart_row:
                return jsonify(ErrorResponse(detail="No active cart found for user.").dict()), 404
            cart_id = cart_row[0]

            # Upsert logic: add 1 to quantity if exists, else insert with quantity 1
            upsert_query = """
            INSERT INTO public.cart_items (cart_id, product_id, quantity)
            VALUES (%s, %s, 1)
            ON CONFLICT (cart_id, product_id)
            DO UPDATE SET quantity = cart_items.quantity + 1;
            """
            cur.execute(upsert_query, (cart_id, data.product_id))
            conn.commit()

        close_conn(conn)
        return jsonify(MessageResponse(message=f"Product {data.product_id} added to cart.").dict()), 200

    except psycopg2.Error as db_err:
        if conn: conn.rollback()
        logger.error(f"DB error adding product {data.product_id} for user {user_id}: {db_err}")
        return jsonify(ErrorResponse(detail=f"Database error: {str(db_err)}").dict()), 500
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Error adding product {data.product_id} for user {user_id}: {e}")
        return jsonify(ErrorResponse(detail="Internal server error.").dict()), 500
    finally:
        if conn and not conn.closed:
            close_conn(conn)

# API 21: Remove one item from Cart
@bp.route('/item/remove', methods=['POST'])
@jwt_required
def remove_product_from_cart_route():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401
        
    try:
        data = CartItemRemoveRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)
    
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # Get the user's cart_id
            cur.execute("SELECT cart_id FROM public.total_carts WHERE user_id = %s LIMIT 1;", (user_id,))
            cart_row = cur.fetchone()
            if not cart_row:
                return jsonify(ErrorResponse(detail="No active cart found for user.").dict()), 404
            cart_id = cart_row[0]

            # Check current quantity
            cur.execute("SELECT quantity FROM public.cart_items WHERE cart_id = %s AND product_id = %s;", (cart_id, data.product_id))
            item_row = cur.fetchone()
            
            if not item_row:
                return jsonify(ErrorResponse(detail=f"Product {data.product_id} not found in cart.").dict()), 404

            if item_row[0] > 1:
                # Decrement quantity by 1
                update_query = "UPDATE public.cart_items SET quantity = quantity - 1 WHERE cart_id = %s AND product_id = %s;"
                cur.execute(update_query, (cart_id, data.product_id))
            else:
                # If quantity is 1, remove the item completely
                delete_query = "DELETE FROM public.cart_items WHERE cart_id = %s AND product_id = %s;"
                cur.execute(delete_query, (cart_id, data.product_id))

            conn.commit()
            
        close_conn(conn)
        return jsonify(MessageResponse(message=f"Product {data.product_id} removed from cart.").dict()), 200
        
    except psycopg2.Error as db_err:
        if conn: conn.rollback()
        logger.error(f"DB error removing product {data.product_id} for user {user_id}: {db_err}")
        return jsonify(ErrorResponse(detail=f"Database error: {str(db_err)}").dict()), 500
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Error removing product {data.product_id} for user {user_id}: {e}")
        return jsonify(ErrorResponse(detail="Internal server error.").dict()), 500
    finally:
        if conn and not conn.closed:
            close_conn(conn)

# API 22: Disconnect Cart
@bp.route('/disconnect', methods=['POST'])
@jwt_required
def disconnect_cart_route():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # Set user_id to NULL for the user's cart and return the cart_id that was disconnected
            update_query = """
            UPDATE public.total_carts
            SET user_id = NULL
            WHERE user_id = %s
            RETURNING cart_id;
            """
            cur.execute(update_query, (user_id,))
            disconnected_cart_row = cur.fetchone()
            conn.commit()
            
        close_conn(conn)

        if disconnected_cart_row:
            cart_id = disconnected_cart_row[0]
            return jsonify(MessageResponse(message=f'Cart {cart_id} disconnected successfully.').dict()), 200
        else:
            # This case means the user was not connected to any cart to begin with.
            return jsonify(ErrorResponse(detail='No active cart found for this user to disconnect.').dict()), 404

    except Exception as e:
        logger.error(f"Error disconnecting cart for user {user_id}: {e}")
        if conn:
            conn.rollback()
            if not conn.closed:
                close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error during disconnect.').dict()), 500 
