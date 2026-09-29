def test_database_connection():
    """Database connection works"""
    from app import get_db
    connection = get_db()
    assert connection is not None
    connection.close()


def test_products_exist():
    """Products list is populated"""
    from app import PRODUCTS
    assert len(PRODUCTS) > 100


def test_users_table_exists():
    """Users table exists in database"""
    from app import get_db
    connection = get_db()
    result = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    connection.close()
    assert result is not None


def test_product_status_table_exists():
    """Product status table exists"""
    from app import get_db
    connection = get_db()
    result = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='product_status'"
    ).fetchone()
    connection.close()
    assert result is not None