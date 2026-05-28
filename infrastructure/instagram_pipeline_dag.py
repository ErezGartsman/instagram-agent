from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'erez_data_engineer',
    'depends_on_past': False,
    'start_date': datetime(2026, 4, 1),
    'email_on_failure': True, 
    'email': ['erezkim1234@gmail.com'], 
    'retries': 2, 
    'retry_delay': timedelta(minutes=5), 
}

with DAG(
    'instagram_end_to_end_pipeline',
    default_args=default_args,
    description='Automated ETL pipeline for Instagram Data',
    schedule_interval='0 8 * * *', 
    catchup=False
) as dag:

    task_scrape_instagram = BashOperator(
        task_id='run_instagram_scraper',
        bash_command='python "C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\comments_single_only.py"'
    )

    task_load_to_snowflake = BashOperator(
        task_id='load_data_to_snowflake',
        bash_command='python "C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\dbt_projects\load_data_to_snowflake.py"'
    )

    task_run_dbt = BashOperator(
        task_id='run_dbt_transformations',
        bash_command='cd "C:/Users/Erez/OneDrive - Bar-Ilan University - Students/Desktop/instagram project/dbt_projects/my_first_dbt_project" && "C:/Users/Erez/AppData/Roaming/Python/Python313/Scripts/dbt.exe" run'
    )

    task_refresh_powerbi = BashOperator(
        task_id='refresh_powerbi_dashboard',
        bash_command='echo "Triggering Power BI REST API to refresh dataset..."'
    )

    task_scrape_instagram >> task_load_to_snowflake >> task_run_dbt >> task_refresh_powerbi