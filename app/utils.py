from flask import jsonify
from pydantic import ValidationError
from .models import ErrorResponse
import decimal
import datetime

def make_response(data, status_code=200):
    """Standard way to create JSON responses."""
    return jsonify(data), status_code

def handle_pydantic_error(error: ValidationError, status_code=400):
    """Handles Pydantic validation errors by returning a structured error response."""
    return jsonify(ErrorResponse(detail=error.errors()).dict()), status_code

def row_to_dict(row, cursor_description):
    """Converts a database row (tuple) to a dictionary using cursor description."""
    if row is None:
        return None
    return dict(zip([col[0] for col in cursor_description], row))

def rows_to_dicts(rows, cursor_description):
    """Converts a list of database rows to a list of dictionaries."""
    return [row_to_dict(row, cursor_description) for row in rows]


def serialize_row(row, cursor_description):
    """Converts a database row to a dictionary, handling specific data types for JSON serialization."""
    if row is None:
        return None
    d = {}
    for i, col in enumerate(cursor_description):
        value = row[i]
        if isinstance(value, decimal.Decimal):
            d[col[0]] = float(value)  # Convert Decimal to float for JSON
        elif isinstance(value, (datetime.date, datetime.datetime)):
            d[col[0]] = value.isoformat() # Convert date/datetime to ISO string
        else:
            d[col[0]] = value
    return d

def serialize_rows(rows, cursor_description):
    """Converts multiple database rows to a list of dictionaries with serialization."""
    if not rows:
        return []
    return [serialize_row(row, cursor_description) for row in rows]

# Example usage within a route:
# from .db import execute_query
# from .utils import serialize_rows
# ...
#    query = "SELECT product_id, product_name, price FROM product WHERE product_id = %s"
#    # Assume execute_query returns (rows, cursor_description) or similar for this example
#    # rows_data, description = execute_query_with_description(query, (product_id,))
#    # serialized_product = serialize_rows(rows_data, description)
#    # return jsonify(serialized_product) 