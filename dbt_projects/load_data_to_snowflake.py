import pandas as pd
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
import os

print("Connecting to Snowflake...")
conn = snowflake.connector.connect(
    user='EREZGARTSMAN',
    password='ErFrJaJu1899?!',  
    account='JUOPCBT-FT21588',
    warehouse='compute_wh',
    database='analytics',
    role='ACCOUNTADMIN'
)

print("Creating and using schema 'dbt_erez'...")
conn.cursor().execute("CREATE SCHEMA IF NOT EXISTS analytics.dbt_erez")
conn.cursor().execute("USE SCHEMA analytics.dbt_erez")

media_dir = r"C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\data\instagram_media\2026-03-03"
followers_dir = r"C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\data\instagram_followers\instagram-erez_gersman-2026-03-10-dNHXArQy\connections\followers_and_following"

print("Loading CSV files...")
df_posts = pd.read_csv(os.path.join(media_dir, "batch_posts.csv"))
df_likers = pd.read_csv(os.path.join(media_dir, "batch_likers.csv"))
df_comments = pd.read_csv(os.path.join(media_dir, "batch_comments.csv"))

print("Loading and concatenating JSON files...")
df_followers_1 = pd.read_json(os.path.join(followers_dir, "followers_1.json"))
df_followers_2 = pd.read_json(os.path.join(followers_dir, "followers_2.json"))
df_followers = pd.concat([df_followers_1, df_followers_2], ignore_index=True)

def clean_columns(df):
    df.columns = df.columns.str.upper().str.replace(' ', '_')
    return df

df_posts = clean_columns(df_posts)
df_likers = clean_columns(df_likers)
df_comments = clean_columns(df_comments)
df_followers = clean_columns(df_followers)

print("Writing data to Snowflake (this might take a few moments)...")

success, num_chunks, num_rows, output = write_pandas(conn, df_posts, 'STG_POSTS', auto_create_table=True)
print(f"Successfully loaded {num_rows} rows into STG_POSTS")

success, num_chunks, num_rows, output = write_pandas(conn, df_likers, 'STG_LIKERS', auto_create_table=True)
print(f"Successfully loaded {num_rows} rows into STG_LIKERS")

success, num_chunks, num_rows, output = write_pandas(conn, df_comments, 'STG_COMMENTS', auto_create_table=True)
print(f"Successfully loaded {num_rows} rows into STG_COMMENTS")

success, num_chunks, num_rows, output = write_pandas(conn, df_followers, 'STG_FOLLOWERS', auto_create_table=True)
print(f"Successfully loaded {num_rows} rows into STG_FOLLOWERS")

conn.close()
print("All done! Data is safely stored in Snowflake's fridge.")