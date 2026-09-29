import sqlite3
import os
from werkzeug.security import generate_password_hash


def get_db():
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DATABASE = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "smartshop.db"))
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():

    connection = get_db()

    
    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            name TEXT NOT NULL,

            surname TEXT NOT NULL,

            email TEXT UNIQUE NOT NULL,

            password TEXT NOT NULL,

            budget REAL DEFAULT 2000,

            role TEXT DEFAULT 'student',

            colour TEXT DEFAULT 'Any',

            style TEXT DEFAULT '',

            preferred_brands TEXT DEFAULT '',

            preferred_colours TEXT DEFAULT '',

            preferred_stores TEXT DEFAULT '',

            hobbies TEXT DEFAULT '',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    
    existing_columns = connection.execute(
        "PRAGMA table_info(users)"
    ).fetchall()

    column_names = [
        column["name"]
        for column in existing_columns
    ]

    

    if "role" not in column_names:
        connection.execute("""
            ALTER TABLE users
            ADD COLUMN role TEXT DEFAULT 'student'
        """)
        print("✅ Added 'role' column to users table")

    if "colour" not in column_names:
        connection.execute("""
            ALTER TABLE users
            ADD COLUMN colour TEXT DEFAULT 'Any'
        """)
        print("✅ Added 'colour' column to users table")

    if "style" not in column_names:
        connection.execute("""
            ALTER TABLE users
            ADD COLUMN style TEXT DEFAULT ''
        """)
        print("✅ Added 'style' column to users table")

    if "preferred_brands" not in column_names:
        connection.execute("""
            ALTER TABLE users
            ADD COLUMN preferred_brands TEXT DEFAULT ''
        """)
        print("✅ Added 'preferred_brands' column to users table")

    if "preferred_colours" not in column_names:
        connection.execute("""
            ALTER TABLE users
            ADD COLUMN preferred_colours TEXT DEFAULT ''
        """)
        print("✅ Added 'preferred_colours' column to users table")

    if "preferred_stores" not in column_names:
        connection.execute("""
            ALTER TABLE users
            ADD COLUMN preferred_stores TEXT DEFAULT ''
        """)
        print("✅ Added 'preferred_stores' column to users table")

    if "hobbies" not in column_names:
        connection.execute("""
            ALTER TABLE users
            ADD COLUMN hobbies TEXT DEFAULT ''
        """)
        print("✅ Added 'hobbies' column to users table")

    # ========================================================
    # CREATE DEFAULT ADMIN USER
    # ========================================================

    admin_email = "admin@smartspend.com"
    admin_password = generate_password_hash("admin123")

    existing_admin = connection.execute(
        "SELECT id FROM users WHERE email = ?", (admin_email,)
    ).fetchone()

    if not existing_admin:
        connection.execute("""
            INSERT INTO users (name, surname, email, password, role, budget)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Admin", "User", admin_email, admin_password, "admin", 99999)
        )
        print("✅ Default admin created: admin@smartspend.com / admin123")
    else:
        print("ℹ️ Admin user already exists")

    
    manager_email = "manager@smartspend.com"
    manager_password = generate_password_hash("manager123")

    existing_manager = connection.execute(
        "SELECT id FROM users WHERE email = ?", (manager_email,)
    ).fetchone()

    if not existing_manager:
        connection.execute("""
            INSERT INTO users (name, surname, email, password, role, budget)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("Store", "Manager", manager_email, manager_password, "store_manager", 5000)
        )
        print("✅ Default store manager created: manager@smartspend.com / manager123")
    else:
        print("ℹ️ Store manager already exists")

    

    connection.execute("""
        CREATE TABLE IF NOT EXISTS search_history (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            query TEXT,

            budget REAL,

            colour TEXT,

            product_id INTEGER,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(user_id)
                REFERENCES users(id)
        )
    """)

    

    connection.execute("""
        CREATE TABLE IF NOT EXISTS shopping_history (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            product_id INTEGER NOT NULL,

            product_name TEXT NOT NULL,

            price REAL NOT NULL,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(user_id)
                REFERENCES users(id)
        )
    """)

    
    connection.execute("""
        CREATE TABLE IF NOT EXISTS product_status (

            product_id INTEGER PRIMARY KEY,

            status TEXT NOT NULL DEFAULT 'In Stock',

            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS stock_alerts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id INTEGER NOT NULL,

            product_id INTEGER NOT NULL,

            product_name TEXT NOT NULL,

            status TEXT DEFAULT 'pending',

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY(user_id)
                REFERENCES users(id)
        )
    """)

    connection.commit()
    connection.close()

    print("=" * 50)
    print("✅ Database initialized successfully!")
    print("=" * 50)
    print("\n📋 Default Login Credentials:")
    print("   👑 Admin:    admin@smartspend.com / admin123")
    print("   🏪 Manager:  manager@smartspend.com / manager123")
    print("   👨‍🎓 Student:  (Register as new user)")
    print("=" * 50)


if __name__ == "__main__":
    init_db()