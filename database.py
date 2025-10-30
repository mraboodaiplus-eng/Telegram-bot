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
                is_frozen INTEGER DEFAULT 0,
                debt_amount REAL DEFAULT 0.0,
                # subscription_status and subscription_end_date are kept for compatibility but will be unused
                subscription_status TEXT DEFAULT 'commission',
                subscription_end_date DATETIME NULL
            )
        """)
        await db.commit()

async def get_user(user_id):
    """Fetches a user's record from the database."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        db.row_factory = aiosqlite.Row
        # Select all columns, including the new ones (is_frozen, debt_amount)
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = await cursor.fetchone()
        return user

async def add_new_user(user_id, user_type='client'):
    """Adds a new user to the database."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, user_type) VALUES (?, ?)",
            (user_id, user_type)
        )
        await db.commit()

async def update_subscription_status(user_id, status, end_date=None):
    """Updates a user's subscription status and end date (Kept for compatibility)."""
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
    """Checks if the user is allowed to trade (not frozen)."""
    if not user_record:
        return False
    
    # Under the new commission model, a user is active if they are not frozen.
    # The 'is_frozen' column will be 0 (False) for active users.
    return user_record['is_frozen'] == 0

# --- NEW DEBT MANAGEMENT FUNCTIONS ---

async def update_debt(user_id, amount_to_add):
    """Adds or subtracts from the user's debt amount."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "UPDATE users SET debt_amount = debt_amount + ? WHERE user_id = ?",
            (amount_to_add, user_id)
        )
        await db.commit()

async def set_frozen_status(user_id, is_frozen_status):
    """Sets the user's frozen status (1 for frozen, 0 for unfrozen)."""
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            "UPDATE users SET is_frozen = ? WHERE user_id = ?",
            (is_frozen_status, user_id)
        )
        await db.commit()

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

