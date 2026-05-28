{{ config(materialized='table') }}

WITH clean_posts AS (
    SELECT * FROM {{ ref('instagram_posts_clean') }}
),

likes_grouped AS (
    SELECT 
        post_shortcode,
        COUNT(*) as total_likes
    FROM {{ ref('stg_likers') }}
    GROUP BY post_shortcode
),

comments_grouped AS (
    SELECT 
        post_shortcode,
        COUNT(*) as total_comments
    FROM {{ ref('stg_comments') }}
    GROUP BY post_shortcode
)

SELECT 
    p.post_shortcode,
    p.post_url,
    p.posted_at,
    COALESCE(l.total_likes, 0) as total_likes,
    COALESCE(c.total_comments, 0) as total_comments
FROM clean_posts p
LEFT JOIN likes_grouped l ON p.post_shortcode = l.post_shortcode
LEFT JOIN comments_grouped c ON p.post_shortcode = c.post_shortcode