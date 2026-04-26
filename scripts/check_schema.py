import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='articles' AND column_name='image_url'")
print('image_url column exists:', bool(cur.fetchone()))
conn.close()
