{{ config(materialized='table') }}

SELECT 
    post_shortcode,
    post_url,
    posted_at_date as posted_at
FROM {{ ref('stg_posts') }}
WHERE post_shortcode IS NOT NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY post_shortcode ORDER BY posted_at_date DESC) = 1