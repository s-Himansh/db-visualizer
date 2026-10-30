"""A small online-shop database for first-run exploration: it has real relationships (including a table that points
at itself), so the schema map and link-following have something to show. Deterministic: same data every time."""
import random
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id)
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    price REAL NOT NULL,
    in_stock INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    country TEXT,
    signed_up TEXT,
    referred_by INTEGER REFERENCES customers(id),
    preferences TEXT
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    status TEXT NOT NULL,
    placed_at TEXT NOT NULL,
    total REAL NOT NULL DEFAULT 0
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL
);
CREATE TABLE shipments (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    carrier TEXT,
    shipped_at TEXT,
    delivered_at TEXT
);
CREATE TABLE reviews (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    rating INTEGER NOT NULL,
    body TEXT
);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_reviews_product ON reviews(product_id);
CREATE VIEW revenue_by_country AS
    SELECT c.country, COUNT(DISTINCT o.id) AS orders, ROUND(SUM(o.total), 2) AS revenue
    FROM orders o JOIN customers c ON c.id = o.customer_id
    WHERE o.status != 'cancelled' GROUP BY c.country;
"""

CATEGORIES = [(1, 'Home', None), (2, 'Kitchen', 1), (3, 'Garden', 1), (4, 'Electronics', None), (5, 'Audio', 4),
              (6, 'Office', None), (7, 'Stationery', 6), (8, 'Furniture', 6)]
PRODUCTS = [('Kettle', 2, 29), ('Toaster', 2, 39), ('Chef knife', 2, 54), ('Cast iron pan', 2, 48), ('Blender', 2, 72),
            ('Garden hose', 3, 24), ('Pruning shears', 3, 19), ('Planter set', 3, 33), ('Watering can', 3, 14),
            ('Headphones', 5, 120), ('Bluetooth speaker', 5, 65), ('Turntable', 5, 210), ('Earbuds', 5, 49),
            ('Power bank', 4, 35), ('USB-C hub', 4, 42), ('Webcam', 4, 58), ('Mechanical keyboard', 4, 95),
            ('Notebook', 7, 6), ('Fountain pen', 7, 28), ('Desk organiser', 7, 17), ('Sticky notes', 7, 4),
            ('Standing desk', 8, 380), ('Office chair', 8, 245), ('Bookshelf', 8, 130), ('Monitor arm', 8, 79),
            ('Desk lamp', 6, 36), ('Whiteboard', 6, 44), ('Paper shredder', 6, 88), ('Label maker', 6, 31),
            ('Wall clock', 1, 22)]
FIRST = ['Ava', 'Liam', 'Noah', 'Mia', 'Ethan', 'Zoe', 'Omar', 'Isla', 'Leo', 'Nina', 'Ravi', 'Sofia', 'Kenji', 'Amara',
         'Lucas', 'Priya', 'Mateo', 'Hana', 'Jonas', 'Layla']
LAST = ['Chen', 'Patel', 'Garcia', 'Rossi', 'Kim', 'Müller', 'Haddad', 'Novak', 'Silva', 'Okafor', 'Sharma', 'Dubois',
        'Tanaka', 'Mensah', 'Berg', 'Kapoor', 'Reyes', 'Sato', 'Weber', 'Nasser']
COUNTRIES = ['IN', 'US', 'DE', 'BR', 'NG', 'JP', 'FR', 'GB']
STATUSES = ['delivered'] * 6 + ['shipped'] * 2 + ['processing', 'cancelled']
CARRIERS = ['DHL', 'UPS', 'FedEx', 'BlueDart']
REVIEWS = ['Does exactly what it says.', 'Arrived quickly, well packed.', 'A bit pricey but worth it.', 'Broke after a month.',
           'Love it.', 'Not what I expected.', 'Great value.', 'Would buy again.']


def build_sample(path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.building')
    tmp.unlink(missing_ok=True)
    rnd = random.Random(2026)
    day = lambda n: f'2026-{1 + n // 28 % 9:02d}-{1 + n % 28:02d}'

    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    db.executemany('INSERT INTO categories VALUES (?,?,?)', CATEGORIES)
    db.executemany('INSERT INTO products(name, category_id, price) VALUES (?,?,?)', PRODUCTS)

    customers = []
    for i in range(1, 121):
        name = f'{rnd.choice(FIRST)} {rnd.choice(LAST)}'
        referred = rnd.randint(1, i - 1) if i > 10 and rnd.random() < 0.3 else None
        prefs = '{"newsletter": true, "theme": "dark"}' if rnd.random() < 0.35 else None
        customers.append((i, name, f'{name.lower().replace(" ", ".")}{i}@example.com', rnd.choice(COUNTRIES),
                          day(rnd.randint(0, 200)), referred, prefs))
    db.executemany('INSERT INTO customers VALUES (?,?,?,?,?,?,?)', customers)

    order_id = item_id = ship_id = 0
    for _ in range(420):
        order_id += 1
        status = rnd.choice(STATUSES)
        placed = day(rnd.randint(0, 220))
        total = 0.0
        for _ in range(rnd.randint(1, 4)):
            item_id += 1
            pid = rnd.randint(1, len(PRODUCTS))
            qty = rnd.randint(1, 3)
            price = PRODUCTS[pid - 1][2]
            total += qty * price
            db.execute('INSERT INTO order_items VALUES (?,?,?,?,?)', (item_id, order_id, pid, qty, price))
        db.execute('INSERT INTO orders VALUES (?,?,?,?,?)', (order_id, rnd.randint(1, 120), status, placed, round(total, 2)))
        if status in ('shipped', 'delivered'):
            ship_id += 1
            shipped = day(rnd.randint(0, 220))
            db.execute('INSERT INTO shipments VALUES (?,?,?,?,?)',
                       (ship_id, order_id, rnd.choice(CARRIERS), shipped, shipped if status == 'delivered' else None))
    for i in range(1, 181):
        db.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',
                   (i, rnd.randint(1, len(PRODUCTS)), rnd.randint(1, 120), rnd.randint(1, 5), rnd.choice(REVIEWS)))
    db.commit()
    db.close()
    tmp.replace(path)
    return path
