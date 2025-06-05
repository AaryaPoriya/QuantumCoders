# Smart Cart Flask API

This project implements the backend APIs for the Smart Cart system using Flask and PostgreSQL.

## Project Structure

```
/flask-smart-cart/
|-- app/                  # Main application package
|   |-- __init__.py       # Flask app factory
|   |-- routes/           # API Blueprints
|   |   |-- __init__.py
|   |   |-- auth_routes.py
|   |   |-- cart_routes.py
|   |   |-- product_routes.py
|   |   |-- user_routes.py
|   |   |-- order_routes.py
|   |   |-- misc_routes.py
|   |-- models.py         # Pydantic models for request/response
|   |-- db.py             # Database connection and utilities
|   |-- auth.py           # Authentication (JWT, OTP) utilities
|   |-- utils.py          # General helper functions
|-- run.py                # Script to run the Flask development server (also used by Gunicorn)
|-- requirements.txt      # Python dependencies
|-- .env.example          # Example environment variables (copy to .env)
|-- Procfile              # Instructions for hosting platforms (e.g., to use Gunicorn)
|-- README.md             # This file
```

## Setup

1.  **Clone the repository (if applicable)**

2.  **Create a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows
    .\venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up PostgreSQL Database:**
    *   Ensure you have PostgreSQL installed and running.
    *   Create a database for this project (e.g., `smart_cart_db`).
    *   Run the SQL schema provided in the initial query to create the tables.

5.  **Configure Environment Variables:**
    *   Copy `.env.example` to a new file named `.env` in the project root:
        ```bash
        cp .env.example .env 
        ```
    *   Edit `.env` and update the following variables with your actual settings:
        *   `DATABASE_URL`: Your PostgreSQL connection string (e.g., `postgresql://username:password@host:port/database_name`).
        *   `SECRET_KEY`: A strong, random secret key for Flask session management.
        *   `JWT_SECRET_KEY`: A different strong, random secret key for JWT generation.
        *   `FIXED_OTP` (optional, for testing): You can keep the default or change it.

## Running the Application

### For Development

Once the setup is complete, you can run the Flask development server:

```bash
flask run
# or
python run.py
```

The API will typically be available at `http://127.0.0.1:5000/` (or the port specified by `flask run`).

### For Production (using Gunicorn)

This application is configured to be run with Gunicorn in a production environment.

1.  **Install Gunicorn** (if not already done via `requirements.txt`):
    ```bash
    pip install gunicorn
    ```

2.  **Run with Gunicorn:**
    A basic command to run Gunicorn locally for testing the production setup:
    ```bash
    gunicorn run:app
    ```
    This will typically start Gunicorn on `http://127.0.0.1:8000`.

    A more production-like command, specifying workers and binding:
    ```bash
    gunicorn --workers 3 --bind 0.0.0.0:5001 run:app
    ```
    *   Replace `3` with an appropriate number of workers for your server (e.g., `(2 * CPU_CORES) + 1`).
    *   Replace `5001` with the port you want Gunicorn to listen on.

3.  **Procfile:**
    The included `Procfile` (`web: gunicorn run:app`) is used by many hosting platforms (like Render, Heroku) to automatically start your application with Gunicorn. You usually don't run this command directly if your platform supports Procfiles.

## API Endpoints

Refer to the route definitions in the `app/routes/` directory for details on available API endpoints. Key prefixes include:
*   `/auth/...`
*   `/user/...`
*   `/products/...`
*   `/cart/...`
*   `/orders/...`
*   `/misc/...`

Example: `POST /auth/verify_mobile`

## Notes for Production Deployment (Recap)

*   **WSGI Server:** Use Gunicorn (as configured) or another production-grade WSGI server.
*   **Environment Variables:** Set `FLASK_ENV='production'` and all secret keys (`SECRET_KEY`, `JWT_SECRET_KEY`, `DATABASE_URL`) as environment variables on your hosting platform. **Do not commit your `.env` file.**
*   **OTP System:** Replace the `FIXED_OTP` with a real OTP generation and delivery mechanism (e.g., SMS gateway).
*   **HTTPS:** Ensure your application is served over HTTPS.
*   **CORS:** Configure CORS appropriately for your production frontend domain.
*   **Logging & Monitoring:** Set up production-level logging and error tracking.
*   **Database:** Use your production database and ensure it's backed up.

## Notes

*   **Error Handling:** The API uses Pydantic for request validation and provides structured JSON error responses.
*   **Database Transactions:** Transaction management (commit/rollback) is handled within individual route functions, typically using a single connection and cursor per request for simplicity. For more complex scenarios spanning multiple helper functions, connection and cursor management might need further refinement.
*   **OTP for New Users:** The current OTP flow for new users marks a mobile number as verified in the session. The `create_profile` API then checks this session state. Ensure your client-side handles this flow by calling `create_profile` shortly after a successful OTP verification for a new number.
*   **ESP32 Cart Updates:** The `/cart/esp32/add_item` endpoint is designed for the ESP32. Consider using API key authentication for devices like ESP32 if JWT is not feasible.
*   **Shortest Path API:** The `/cart/shortest_path` API is currently a placeholder and returns dummy data. A proper graph traversal algorithm (e.g., Dijkstra's or A*) would need to be implemented based on your store layout data. 