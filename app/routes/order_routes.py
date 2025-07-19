from flask import Blueprint, request, jsonify
from pydantic import ValidationError
from app.models import (
    CheckoutResponse, OrderResponse, DetailOrderItemResponse, Product as ProductModel,
    ErrorResponse, MessageResponse
)
from app.db import execute_query # Using the global execute_query for simplicity here
from app.auth import jwt_required, get_current_user_id
from app.utils import handle_pydantic_error, serialize_row, serialize_rows
import logging
import psycopg2

logger = logging.getLogger(__name__)
bp = Blueprint('order', __name__, url_prefix='/orders')

# API 19: Checkout
@bp.route('/checkout', methods=['POST'])
@jwt_required
def checkout_route():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401

    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            # 1. Find the user's active cart
            cur.execute("SELECT cart_id FROM public.total_carts WHERE user_id = %s LIMIT 1;", (user_id,))
            cart_row = cur.fetchone()
            if not cart_row:
                close_conn(conn)
                return jsonify(ErrorResponse(detail='No active cart to checkout.').dict()), 404
            cart_id = cart_row[0]

            # 2. Get cart items and calculate totals
            items_query = """
            SELECT ci.product_id, ci.quantity, p.price, p.discounted_price, p.product_name
            FROM public.cart_items ci
            JOIN public.product p ON ci.product_id = p.product_id
            WHERE ci.cart_id = %s;
            """
            cur.execute(items_query, (cart_id,))
            cart_items_raw = cur.fetchall()
            
            if not cart_items_raw:
                close_conn(conn)
                return jsonify(ErrorResponse(detail='Cart is empty. Nothing to checkout.').dict()), 400

            total_products_count = 0
            total_original_price = 0.0
            total_discounted_price = 0.0
            order_items_for_db = []

            for item_data in cart_items_raw:
                # item_data structure: product_id, quantity, price, discounted_price, product_name
                # Need to map these to column names if serialize_row is not used or adapt access
                # Assuming direct tuple access: product_id=0, quantity=1, price=2, discounted_price=3
                product_id, quantity, price, discounted_price_val, product_name = item_data
                price = float(price)
                discounted_price_val = float(discounted_price_val) if discounted_price_val is not None else price
                
                total_products_count += quantity
                total_original_price += price * quantity
                total_discounted_price += discounted_price_val * quantity
                
                order_items_for_db.append({
                    'product_id': product_id,
                    'quantity': quantity,
                    'price': price,
                    'discounted_price': discounted_price_val
                })
            
            # 3. Insert into orders table
            insert_order_query = """
            INSERT INTO public.orders (user_id, total_products, total_price, discounted_price)
            VALUES (%s, %s, %s, %s) RETURNING order_id;
            """
            cur.execute(insert_order_query, (user_id, total_products_count, total_original_price, total_discounted_price))
            order_id_row = cur.fetchone()
            if not order_id_row:
                conn.rollback()
                close_conn(conn)
                return jsonify(ErrorResponse(detail='Failed to create order record.').dict()), 500
            new_order_id = order_id_row[0]

            # 4. Insert into detail_order table
            insert_detail_query = """
            INSERT INTO public.detail_order (order_id, product_id, quantity, price, discounted_price)
            VALUES (%s, %s, %s, %s, %s);
            """
            for item_db in order_items_for_db:
                cur.execute(insert_detail_query, (
                    new_order_id, item_db['product_id'], item_db['quantity'], 
                    item_db['price'], item_db['discounted_price']
                ))
            
            # 5. Clear cart items (from cart_items table)
            cur.execute("DELETE FROM public.cart_items WHERE cart_id = %s;", (cart_id,))
            # Optionally, also delete the total_carts entry or reset its weight
            cur.execute("DELETE FROM public.total_carts WHERE cart_id = %s;", (cart_id,))
            # If total_carts is to be kept for some reason, reset weight: 
            # cur.execute("UPDATE public.total_carts SET cart_weight = 0 WHERE cart_id = %s;", (cart_id,))

            conn.commit()
        close_conn(conn)
        
        return jsonify(CheckoutResponse(
            order_id=new_order_id,
            user_id=user_id,
            total_products=total_products_count,
            total_price=total_original_price,
            discounted_price=total_discounted_price,
            message="Checkout successful. Order created."
        ).dict()), 201

    except psycopg2.Error as db_err:
        logger.error(f"Database error during checkout for user {user_id}: {db_err}")
        if conn: conn.rollback()
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail=f'Database error during checkout: {str(db_err)}').dict()), 500
    except Exception as e:
        logger.error(f"Error during checkout for user {user_id}: {e}")
        if conn: conn.rollback()
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error during checkout.').dict()), 500

# API: Fetch User's Past Orders
@bp.route('/history', methods=['GET'])
@jwt_required
def get_order_history():
    user_id = get_current_user_id()
    if not user_id:
        return jsonify(ErrorResponse(detail='Authentication required.').dict()), 401

    query = """
    SELECT 
        o.order_id, o.user_id, o.total_products, o.total_price, o.discounted_price,
        (
            SELECT json_agg(
                json_build_object(
                    'product_id', od.product_id,
                    'quantity', od.quantity,
                    'price', od.price,
                    'discounted_price', od.discounted_price,
                    'product_name', p.product_name
                )
            )
            FROM public.detail_order od
            JOIN public.product p ON od.product_id = p.product_id
            WHERE od.order_id = o.order_id
        ) as items
    FROM public.orders o
    WHERE o.user_id = %s
    ORDER BY o.order_id DESC;
    """
    
    conn = None
    try:
        from app.db import get_conn, close_conn
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(query, (user_id,))
            rows = cur.fetchall()
            
            orders_list = []
            if rows:
                serialized_orders = serialize_rows(rows, cur.description)
                for order_data in serialized_orders:
                    # Items are already fetched as a JSON array from the DB
                    items_list = order_data.get('items') or []
                    order_data['items'] = [DetailOrderItemResponse(**item) for item in items_list]
                    orders_list.append(OrderResponse(**order_data))

        close_conn(conn)
        return jsonify([o.dict() for o in orders_list]), 200
    except Exception as e:
        logger.error(f"Error fetching order history for user {user_id}: {e}")
        if conn and not conn.closed: close_conn(conn)
        return jsonify(ErrorResponse(detail='Internal server error').dict()), 500 