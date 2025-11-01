# -*- coding: utf-8 -*-
import aiosqlite
import os
import datetime

DATABASE_NAME = "database.db"

async def init_db():
    """Initializes the database and creates the users table if it doesn't exist."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                user_type TEXT DEFAULT 'client',
                api_key TEXT NULL,
                api_secret TEXT NULL,
                subscription_status TEXT DEFAULT 'inactive',
                subscription_end_date DATETIME NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS grids (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                symbol TEXT NOT NULL,
                lower_bound REAL NOT NULL,
                upper_bound REAL NOT NULL,
                num_grids INTEGER NOT NULL,
                amount_per_order REAL NOT NULL,
                status TEXT DEFAULT 'active',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()

async def get_user(user_id):
    """Fetches a user's record from the database."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        # Convert Row object to dict to ensure compatibility with bot.py access methods
        return dict(user) if user else None

async def add_new_user(user_id, user_type='client'):
    """Adds a new user to the database."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, user_type) VALUES (?, ?)",
            (user_id, user_type)
        )
        await db.commit()

async def update_subscription_status(user_id, status, end_date=None):
    """Updates a user's subscription status and end date."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "UPDATE users SET subscription_status = ?, subscription_end_date = ? WHERE user_id = ?",
            (status, end_date, user_id)
        )
        await db.commit()

async def update_api_keys(user_id, api_key, api_secret):
    """Updates a user's API keys."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "UPDATE users SET api_key = ?, api_secret = ? WHERE user_id = ?",
            (api_key, api_secret, user_id)
        )
        await db.commit()

async def setup_vip_api_keys(user_id, api_key, api_secret):
    """Sets up API keys for a VIP user, only if they are not already set."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, api_key, api_secret) VALUES (?, ?, ?)",
            (user_id, api_key, api_secret)
        )
        await db.execute(
            "UPDATE users SET api_key = ?, api_secret = ? WHERE user_id = ? AND api_key IS NULL",
            (api_key, api_secret, user_id)
        )
        await db.commit()

def is_subscription_active(user_record):
    """Checks if the user's subscription is currently active."""
    if not user_record:
        return False
    
    if user_record.get('subscription_status') == 'active':
        end_date_str = user_record.get('subscription_end_date')
        if end_date_str:
            # Convert string to datetime object
            end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')
            # Check if the end date is in the future
            return end_date > datetime.datetime.now()
    
    return False

# Initialize the database file
async def create_initial_db_file():
    """A helper function to create the initial database file."""
    if not os.path.exists(DATABASE_NAME):
        await init_db()

if __name__ == '__main__':
    # Simple test to create the file
    import asyncio
    asyncio.run(create_initial_db_file())
    print(f"Database file '{DATABASE_NAME}' created successfully.")


async def add_new_grid(user_id, symbol, lower_bound, upper_bound, num_grids, amount_per_order):
    """Adds a new grid trading configuration to the database."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO grids (user_id, symbol, lower_bound, upper_bound, num_grids, amount_per_order) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, symbol, lower_bound, upper_bound, num_grids, amount_per_order)
        )
        await db.commit()
        return cursor.lastrowid

async def get_active_grids():
    """Fetches all active grid trading configurations."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM grids WHERE status = 'active'")
        grids = await cursor.fetchall()
        return [dict(grid) for grid in grids]

async def stop_grid(grid_id):
    """Sets the status of a grid to 'stopped'."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "UPDATE grids SET status = 'stopped' WHERE id = ?",
            (grid_id,)
        )
        await db.commit()

async def get_user_grids(user_id):
    """Fetches all grids (active and stopped) for a specific user."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM grids WHERE user_id = ?", (user_id,))
        grids = await cursor.fetchall()
        return [dict(grid) for grid in grids]

async def get_grid_by_id(grid_id):
    """Fetches a specific grid trading configuration by its ID."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM grids WHERE id = ?", (grid_id,))
        grid = await cursor.fetchone()
        return dict(grid) if grid else None
