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

async def update_subscription_status(user_id, status=None, end_date=None, is_frozen=None, debt_amount=None):
    """Updates a user's subscription status, end date, frozen status, and debt amount."""
    updates = []
    params = []
    
    if status is not None:
        updates.append("subscription_status = ?")
        params.append(status)
    if end_date is not None:
        updates.append("subscription_end_date = ?")
        params.append(end_date)
    if is_frozen is not None:
        updates.append("is_frozen = ?")
        params.append(is_frozen)
    if debt_amount is not None:
        updates.append("debt_amount = ?")
        params.append(debt_amount)
        
    if not updates:
        return # Nothing to update

    set_clause = ", ".join(updates)
    params.append(user_id)
    
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute(
            f"UPDATE users SET {set_clause} WHERE user_id = ?",
            tuple(params)
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

