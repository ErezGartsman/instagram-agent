with source as (
    select * from {{ source('instagram_raw', 'raw_posts') }}
),

renamed as (
    select
        post_shortcode,
        post_url,
        COALESCE(
            TRY_TO_DATE(posted_at, 'YYYY-MM-DD'),
            TRY_TO_DATE(posted_at, 'DD/MM/YYYY'),
            TRY_CAST(posted_at AS DATE)
        ) as posted_at_date
    from source
    where post_shortcode is not null 
)

select * from renamed