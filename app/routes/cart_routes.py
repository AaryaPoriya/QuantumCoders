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
from app.pathfinding import AStar, create_grid_from_db
from app.routing_utils import enrich_path
import logging
import psycopg2 # For specific error handling

logger = logging.getLogger(__name__)
bp = Blueprint('cart', __name__, url_prefix='/cart')

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
    
    try:
        data = ShortestPathRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # 1. Get the user's cart and its location
            cur.execute("""
                SELECT cl.x_coord, cl.y_coord 
                FROM public.total_carts tc
                JOIN public.cart_locations cl ON tc.cart_id = cl.cart_id
                WHERE tc.user_id = %s
                ORDER BY cl.updated_at DESC
                LIMIT 1;
            """, (user_id,))
            start_pos_raw = cur.fetchone()
            if not start_pos_raw:
                return jsonify(ErrorResponse(detail='Could not find a connected cart with a location for the user.').dict()), 404
            
            start_x, start_y = float(start_pos_raw[0]), float(start_pos_raw[1])

            # 2. Fetch all store sections to build the navigation grid
            cur.execute("SELECT section_id, section_name, x1, y1, x2, y2 FROM public.store_sections;")
            sections_raw = cur.fetchall()
            sections = [serialize_row(row, cur.description) for row in sections_raw]

            # 3. Fetch product locations for the destinations
            product_ids = [dest.product_id for dest in data.destinations]
            cur.execute("SELECT product_id, x_coord, y_coord, section_id FROM public.product_locations WHERE product_id = ANY(%s);", (product_ids,))
            product_locs_raw = cur.fetchall()
            product_locations = {row[0]: serialize_row(row, cur.description) for row in product_locs_raw}

            # 4. Determine grid size and create solver
            max_x = max(s['x2'] for s in sections) if sections else 100
            max_y = max(s['y2'] for s in sections) if sections else 100
            resolution = 10
            grid = create_grid_from_db(sections, max_x, max_y, resolution=resolution)

            # Add the additional restricted zone to the grid
            restricted_x1, restricted_y1 = int(0.750 * resolution), int(0.725 * resolution)
            restricted_x2, restricted_y2 = int(3.250 * resolution), int(1.250 * resolution)
            for r in range(restricted_y1, restricted_y2 + 1):
                for c in range(restricted_x1, restricted_x2 + 1):
                    if 0 <= r < len(grid) and 0 <= c < len(grid[0]):
                        grid[r][c] = 1

            astar = AStar(grid)
            
            # 5. Calculate path
            full_path_coords = []
            current_pos = (start_x, start_y)
            
            dest_coords = [
                (p_id, product_locations[p_id]['x_coord'], product_locations[p_id]['y_coord']) 
                for p_id in product_ids if p_id in product_locations
            ]
            
            sorted_destinations = sorted(
                dest_coords, 
                key=lambda p: ((p[1] - current_pos[0])**2 + (p[2] - current_pos[1])**2)**0.5
            )

            for _, dest_x, dest_y in sorted_destinations:
                destination_pos = (dest_x, dest_y)
                start_scaled = (current_pos[0] * resolution, current_pos[1] * resolution)
                end_scaled = (destination_pos[0] * resolution, destination_pos[1] * resolution)
                segment = astar.find_path(start_scaled, end_scaled)
                
                if segment:
                    segment_to_add = segment if not full_path_coords else segment[1:]
                    for p in segment_to_add:
                        full_path_coords.append({'x': p[1] / resolution, 'y': p[0] / resolution})
                    last_point_scaled = segment[-1]
                    current_pos = (last_point_scaled[1] / resolution, last_point_scaled[0] / resolution)
                else:
                    logger.warning(f"Could not find path from {current_pos} to {destination_pos}")

            if not full_path_coords:
                return jsonify(ErrorResponse(detail='Could not calculate a valid path.').dict()), 422
            
            # 6. Enrich path with instructions and section IDs
            enriched_path = enrich_path(full_path_coords, product_locations)
            response_path = [PathSegment(**p) for p in enriched_path]

        close_conn(conn)
        return jsonify(ShortestPathResponse(path=response_path).dict()), 200

    except Exception as e:
        logger.error(f"Error calculating shortest path for user {user_id}: {e}")
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

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
