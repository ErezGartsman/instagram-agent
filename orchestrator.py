import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
import pandas as pd
import subprocess
import os

conn = snowflake.connector.connect(
    user='EREZGARTSMAN',
    password='ErFrJaJu1899?!', 
    account='JUOPCBT-FT21588',
    warehouse='COMPUTE_WH',
    database='INSTAGRAM_ANALYTICS',
    schema='RAW'
)

def upload_to_snowflake(file_path, table_name):
    print(f"--- Processing {table_name} ---")
    
    df = pd.read_csv(file_path)
    
    df.columns = [col.upper() for col in df.columns]
    
    conn.cursor().execute(f"TRUNCATE TABLE {table_name}")
    
    success, nchunks, nrows, _ = write_pandas(conn, df, table_name)
    
    if success:
        print(f"Successfully uploaded {nrows} rows to {table_name}.")
    else:
        print(f"Failed to upload to {table_name}.")

def run_dbt():
    """מריץ את פקודות ה-dbt בתוך התיקייה הנכונה"""
    print("\n--- Starting dbt Transformation ---")
    
    dbt_path = r"C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\dbt_projects\instagram_analytics"
    
    try:
        subprocess.run(["dbt", "run"], check=True, cwd=dbt_path)
        subprocess.run(["dbt", "test"], check=True, cwd=dbt_path)
        print("✅ dbt finished successfully!")
    except subprocess.CalledProcessError as e:
        print(f"❌ dbt failed with error: {e}")

if __name__ == "__main__":
    try:
        
        upload_to_snowflake(
            r'C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\data\instagram_media\2026-03-03\batch_posts.csv', 
            'RAW_POSTS'
        )
        
        upload_to_snowflake(
            r'C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\data\instagram_media\2026-03-03\batch_comments.csv', 
            'RAW_COMMENTS'
        )
        
        upload_to_snowflake(
            r'C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\data\instagram_media\2026-03-03\batch_likers.csv', 
            'RAW_LIKERS'
        )
        
        run_dbt()
        
        print("\n✅ All done! Your Power BI is ready for refresh.")
        
    except Exception as e:
        print(f"❌ An error occurred: {e}")
    finally:
        conn.close()