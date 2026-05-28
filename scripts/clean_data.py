import pandas as pd
import os

BASE_OUT_DIR = r"C:\Users\Erez\OneDrive - Bar-Ilan University - Students\Desktop\instagram project\data\instagram_media"
RUN_TAG = "2025-12-22"  
TARGET_DIR = os.path.join(BASE_OUT_DIR, RUN_TAG)

files_to_clean = ["batch_posts.csv", "batch_comments.csv", "batch_likers.csv"]
clean_posts_file = os.path.join(TARGET_DIR, "batch_posts.csv")
processed_file = os.path.join(TARGET_DIR, "processed_shortcodes.txt")

print(f"📂 Targeting folder: {TARGET_DIR}")
print("🧹 Starting cleanup process...")


for filename in files_to_clean:
    full_path = os.path.join(TARGET_DIR, filename)
    
    if os.path.exists(full_path):
        try:
            df = pd.read_csv(full_path)
            original_len = len(df)
            
            df_clean = df.dropna(how='all')
            
            if 'post_shortcode' in df_clean.columns:
                df_clean = df_clean.dropna(subset=['post_shortcode'])
            
            df_clean.to_csv(full_path, index=False, encoding="utf-8-sig")
            
            print(f"✅ Cleaned {filename}: Removed {original_len - len(df_clean)} empty rows.")
        except Exception as e:
            print(f"❌ Error cleaning {filename}: {e}")
    else:
        print(f"⚠️ File not found: {filename}")

if os.path.exists(clean_posts_file):
    print("🔄 Rebuilding processed_shortcodes.txt...")
    try:
        df_posts = pd.read_csv(clean_posts_file)
        
        if 'post_shortcode' in df_posts.columns:
            shortcodes = df_posts['post_shortcode'].dropna().unique()
            
            with open(processed_file, "w", encoding="utf-8") as f:
                for sc in shortcodes:
                    f.write(str(sc).strip() + "\n")
            
            print(f"✅ Automatically restored {len(shortcodes)} posts to {processed_file}")
            print(f"🚀 Ready to continue! The next run will skip these {len(shortcodes)} posts.")
        else:
            print(f"❌ column 'post_shortcode' not found in {clean_posts_file}")
            
    except Exception as e:
        print(f"❌ Error rebuilding processed file: {e}")
else:
    print("❌ Could not find batch_posts.csv to rebuild the list.")

print("🏁 Done.")