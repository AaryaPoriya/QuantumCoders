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
        find_cart_query = "SELECT cart_id FROM public.total_carts WHERE user_id = %s LIMIT 1;"
        cart_row = execute_query(find_cart_query, (user_id,), fetchone=True)

        if cart_row:
            cart_id = cart_row[0]
            return jsonify(CartConnectionResponse(cart_id=cart_id, user_id=user_id, message="Already connected to cart.").dict()), 200
        else:
            create_cart_query = "INSERT INTO public.total_carts (user_id, cart_weight) VALUES (%s, 0) RETURNING cart_id;"
            conn = None
            new_cart_id = None
            from app.db import get_conn, close_conn
            try:
                conn = get_conn()
                with conn.cursor() as cur:
                    cur.execute(create_cart_query, (user_id,))
                    new_cart_row = cur.fetchone()
                    if new_cart_row:
                        new_cart_id = new_cart_row[0]
                    conn.commit()
            except Exception as db_e:
                if conn: conn.rollback()
                raise db_e
            finally:
                if conn: close_conn(conn)
            
            if new_cart_id:
                return jsonify(CartConnectionResponse(cart_id=new_cart_id, user_id=user_id, message="New cart connected successfully.").dict()), 201
            else:
                return jsonify(ErrorResponse(detail='Failed to connect cart.').dict()), 500
    except Exception as e:
        logger.error(f"Error connecting cart for user {user_id}: {e}")
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

# API 14: View Cart
@bp.route('/view', methods=['GET'])
@jwt_required
def view_cart_route():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401

    cart_info_query = "SELECT cart_id, cart_weight FROM public.total_carts WHERE user_id = %s LIMIT 1;"
    
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        cart_id = None
        cart_weight = 0
        items_list = []
        with conn.cursor() as cur:
            cur.execute(cart_info_query, (user_id,))
            cart_info_row = cur.fetchone()
            if not cart_info_row:
                close_conn(conn)
                return jsonify(ErrorResponse(detail='No active cart found for user.').dict()), 404
            cart_id = cart_info_row[0]
            cart_weight = cart_info_row[1] if cart_info_row[1] is not None else 0

            items_query = """
            SELECT ci.cart_items_id, ci.cart_id, ci.product_id, ci.quantity,
                   p.product_name, p.price, p.discounted_price, p.barcode, p.weight as product_weight, p.expiry, p.category_id, p.offer_name
            FROM public.cart_items ci
            JOIN public.product p ON ci.product_id = p.product_id
            WHERE ci.cart_id = %s;
            """
            cur.execute(items_query, (cart_id,))
            rows = cur.fetchall()
            if rows:
                for row_data in rows:
                    serialized_item = serialize_row(row_data, cur.description)
                    product_data = {
                        'product_id': serialized_item['product_id'],
                        'product_name': serialized_item['product_name'],
                        'price': serialized_item['price'],
                        'discounted_price': serialized_item.get('discounted_price'),
                        'barcode': serialized_item['barcode'],
                        'weight': serialized_item.get('product_weight'),
                        'expiry': serialized_item.get('expiry'),
                        'category_id': serialized_item.get('category_id'),
                        'offer_name': serialized_item.get('offer_name')
                    }
                    cart_item = CartItemModel(
                        cart_items_id=serialized_item['cart_items_id'],
                        cart_id=serialized_item['cart_id'],
                        product_id=serialized_item['product_id'],
                        quantity=serialized_item['quantity'],
                        product=ProductModel(**product_data)
                    )
                    items_list.append(cart_item)
        close_conn(conn)
        return jsonify(CartViewResponse(cart_id=cart_id, items=items_list, total_weight=float(cart_weight)).dict()), 200
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
    WHERE pl.product_id = ANY(%s);
    """
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        locations_data = []
        with conn.cursor() as cur:
            cur.execute(query, (product_ids,))
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

# API 18: Get Shortest Path (Placeholder)
@bp.route('/shortest_path', methods=['POST'])
@jwt_required
def get_shortest_path_route():
    try:
        data = ShortestPathRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)
    
    logger.info(f"Shortest path requested from ({data.start_x},{data.start_y}) to {data.destinations}")
    dummy_path = [
        PathSegment(x=data.start_x + 1, y=data.start_y + 1, instruction="Go forward"),
        PathSegment(x=data.start_x + 2, y=data.start_y + 2, instruction="Turn left at next aisle")
    ]
    if data.destinations:
        last_dest_coords = data.destinations[-1]
        dummy_path.append(PathSegment(x=last_dest_coords.get('x', data.start_x+3), y=last_dest_coords.get('y',data.start_y+3), instruction="You have arrived"))

    return jsonify(ShortestPathResponse(path=dummy_path).dict()), 200

# API 20: Add Product Into Cart and Update Cart Weight (for ESP32)
@bp.route('/esp32/add_item', methods=['POST'])
# Consider API Key auth for ESP32 if JWT is complex for it
def update_cart_item_esp32_route():
    try:
        data = Esp32CartUpdateRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    upsert_item_query = """
    INSERT INTO public.cart_items (cart_id, product_id, quantity) 
    VALUES (%s, %s, 1) 
    ON CONFLICT (cart_id, product_id) 
    DO UPDATE SET quantity = cart_items.quantity + 1
    RETURNING cart_items_id;
    """
    update_weight_query = "UPDATE public.total_carts SET cart_weight = %s WHERE cart_id = %s;"
    
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(upsert_item_query, (data.cart_id, data.product_id))
            item_row = cur.fetchone()
            if not item_row:
                conn.rollback()
                close_conn(conn)
                return jsonify(ErrorResponse(detail='Failed to add item to cart.').dict()), 500
            
            cur.execute(update_weight_query, (data.weight, data.cart_id))
            conn.commit()
        close_conn(conn)
        return jsonify(MessageResponse(message=f'Product {data.product_id} added/updated in cart {data.cart_id}, weight updated to {data.weight}.').dict()), 200
    except psycopg2.Error as db_err:
        logger.error(f"Database error updating cart for ESP32 {data.cart_id}: {db_err}")
        if conn: conn.rollback()
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail=f'Database error: {str(db_err)}').dict()), 500
    except Exception as e:
        logger.error(f"Error updating cart for ESP32 {data.cart_id}: {e}")
        if conn: conn.rollback()
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

# API 21: Remove Product From Cart
@bp.route('/item/remove', methods=['POST'])
@jwt_required
def remove_product_from_cart_route():
    user_id = get_current_user_id()
    if not user_id: return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401
    
    try:
        data = CartItemRemoveRequest(**request.json)
    except ValidationError as e:
        return handle_pydantic_error(e)

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # Get user's active cart_id using the existing cursor for the transaction
            cur.execute("SELECT cart_id FROM public.total_carts WHERE user_id = %s LIMIT 1;", (user_id,))
            cart_id_row = cur.fetchone()
            if not cart_id_row: 
                close_conn(conn)
                return jsonify(ErrorResponse(detail='No active cart found for user.').dict()), 404
            cart_id = cart_id_row[0]

            get_qty_query = "SELECT quantity FROM public.cart_items WHERE cart_id = %s AND product_id = %s;"
            cur.execute(get_qty_query, (cart_id, data.product_id))
            item_row = cur.fetchone()

            if not item_row:
                close_conn(conn)
                return jsonify(ErrorResponse(detail=f'Product {data.product_id} not found in cart.').dict()), 404
            current_quantity = item_row[0]
            
            if current_quantity > 1:
                update_qty_query = "UPDATE public.cart_items SET quantity = quantity - 1 WHERE cart_id = %s AND product_id = %s;"
                cur.execute(update_qty_query, (cart_id, data.product_id))
            else:
                delete_item_query = "DELETE FROM public.cart_items WHERE cart_id = %s AND product_id = %s;"
                cur.execute(delete_item_query, (cart_id, data.product_id))
            conn.commit()
        close_conn(conn)
        return jsonify(MessageResponse(message=f'Product {data.product_id} quantity updated/removed from cart {cart_id}.').dict()), 200
    except Exception as e:
        logger.error(f"Error removing item {data.product_id if 'data' in locals() else 'N/A'} from cart: {e}")
        if conn: conn.rollback()
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500

# API 22: Disconnect Cart
@bp.route('/disconnect', methods=['POST'])
@jwt_required
def disconnect_cart_route():
    user_id = get_current_user_id()
    if not user_id: return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT cart_id FROM public.total_carts WHERE user_id = %s LIMIT 1;", (user_id,))
            cart_id_row = cur.fetchone()
            if not cart_id_row:
                close_conn(conn)
                return jsonify(ErrorResponse(detail='No active cart found for this user to disconnect.').dict()), 404
            cart_id = cart_id_row[0]

            delete_cart_query = "DELETE FROM public.total_carts WHERE cart_id = %s AND user_id = %s;"
            cur.execute(delete_cart_query, (cart_id, user_id))
            conn.commit()
            
            cur.execute("SELECT cart_id FROM public.total_carts WHERE cart_id = %s;", (cart_id,))
            still_exists = cur.fetchone()
        close_conn(conn)

        if not still_exists:
             return jsonify(MessageResponse(message=f'Cart {cart_id} disconnected and cleared successfully.').dict()), 200
        else:
            logger.warning(f"Cart {cart_id} was not deleted upon disconnect attempt for user {user_id}")
            return jsonify(ErrorResponse(detail='Failed to disconnect cart. Cart might still exist.').dict()), 500
    except Exception as e:
        logger.error(f"Error disconnecting cart for user {user_id}: {e}")
        if conn: conn.rollback()
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error during disconnect.').dict()), 500 