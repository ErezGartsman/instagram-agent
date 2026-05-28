from selenium import webdriver as web
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random
import csv
import json
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.options import Options

# Instagram credentials
bot_username = 'lapicanteff'
bot_password = 'Gv26041987@'

class InstagramPostScraper:
    def __init__(self, username, password):
        self.username = username
        self.password = password
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Remove headless to see what's happening
        # options.add_argument("--headless")
        self.browser = web.Chrome(options=options)
        self.browser.set_window_size(900, 900)

    def close_browser(self):
        self.browser.close()
        self.browser.quit()

    def login(self):
        browser = self.browser
        try:
            browser.get('https://www.instagram.com')
            wait = WebDriverWait(browser, 10)

            # Wait for and find username input
            username_input = wait.until(EC.presence_of_element_located((By.NAME, 'username')))
            username_input.clear()
            username_input.send_keys(self.username)
            time.sleep(random.randrange(2, 4))

            # Wait for and find password input
            password_input = wait.until(EC.presence_of_element_located((By.NAME, 'password')))
            password_input.clear()
            password_input.send_keys(self.password)
            time.sleep(random.randrange(1, 2))
            password_input.send_keys(Keys.ENTER)
            time.sleep(random.randrange(3, 5))
            print(f'[{self.username}] Successfully logged on!')
        except Exception as ex:
            print(f'[{self.username}] Authorization fail: {ex}')
            self.close_browser()

    def scrape_user_posts(self, target_username, max_posts=50):
        """Scrape posts from a specific user's profile"""
        browser = self.browser
        wait = WebDriverWait(browser, 15)

        print(f"Scraping posts from @{target_username}...")

        # Navigate to user's profile
        browser.get(f'https://instagram.com/{target_username}')
        time.sleep(random.randrange(3, 5))

        # Check if we got redirected to login page (session expired)
        current_url = browser.current_url
        if 'accounts/login' in current_url or current_url == 'https://www.instagram.com/':
            print("Session expired, logging in again...")
            self.login()
            time.sleep(3)
            browser.get(f'https://instagram.com/{target_username}')
            time.sleep(random.randrange(3, 5))

        # Wait for page to load
        try:
            wait.until(EC.presence_of_element_located((By.XPATH, "//header")))
        except:
            print(f"Profile page didn't load properly for user {target_username}")
            return []

        posts_data = []

        try:
            # Find all post links on the profile
            post_links = []
            scroll_attempts = 0
            max_scroll_attempts = 20

            print("Collecting post links...")

            while len(post_links) < max_posts and scroll_attempts < max_scroll_attempts:
                # Find post elements
                post_elements = browser.find_elements(By.XPATH, "//a[contains(@href, '/p/')]")

                # Extract unique URLs
                current_links = set()
                for element in post_elements:
                    href = element.get_attribute('href')
                    if href and '/p/' in href:
                        current_links.add(href)

                # Add new links
                new_links = current_links - set(post_links)
                post_links.extend(list(new_links))

                if len(new_links) == 0:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0  # Reset if we found new posts

                print(f"Found {len(post_links)} post links so far...")

                # Scroll down to load more posts
                browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.randrange(2, 4))

                if len(post_links) >= max_posts:
                    break

            print(f"Found {len(post_links)} total post links")

            # Limit to requested number
            post_links = post_links[:max_posts]

            # Now visit each post to get details
            for i, post_url in enumerate(post_links):
                try:
                    print(f"Scraping post {i+1}/{len(post_links)}: {post_url}")

                    browser.get(post_url)
                    time.sleep(random.randrange(2, 4))

                    post_data = self.extract_post_data(post_url)
                    if post_data:
                        posts_data.append(post_data)

                    # Add delay between posts
                    time.sleep(random.randrange(1, 3))

                except Exception as e:
                    print(f"Error scraping post {post_url}: {e}")
                    continue

        except Exception as e:
            print(f"Error during post collection: {e}")

        return posts_data

    def extract_post_data(self, post_url):
        """Extract data from individual post page"""
        browser = self.browser

        try:
            post_data = {
                'url': post_url,
                'caption': '',
                'likes': 0,
                'comments': 0,
                'timestamp': '',
                'image_urls': [],
                'video_urls': []
            }

            # Extract post ID from URL
            if '/p/' in post_url:
                post_data['post_id'] = post_url.split('/p/')[1].split('/')[0]

            # Try to find caption
            try:
                caption_selectors = [
                    "//meta[@property='og:description']",
                    "//span[contains(@class, '_91t')]//span",
                    "//div[@data-testid='post-caption']//span"
                ]

                for selector in caption_selectors:
                    try:
                        if selector.startswith("//meta"):
                            caption_element = browser.find_element(By.XPATH, selector)
                            post_data['caption'] = caption_element.get_attribute('content')
                        else:
                            caption_element = browser.find_element(By.XPATH, selector)
                            post_data['caption'] = caption_element.text

                        if post_data['caption']:
                            break
                    except:
                        continue

            except Exception as e:
                print(f"Could not find caption: {e}")

            # Try to find like count
            try:
                like_selectors = [
                    "//span[contains(text(), 'likes')]",
                    "//button[contains(@class, 'like')]//span",
                    "//span[contains(@class, 'count')]"
                ]

                for selector in like_selectors:
                    try:
                        like_element = browser.find_element(By.XPATH, selector)
                        like_text = like_element.text
                        # Extract number from text like "1,234 likes"
                        if 'like' in like_text.lower():
                            like_num = ''.join(filter(str.isdigit, like_text.split()[0]))
                            if like_num:
                                post_data['likes'] = int(like_num)
                                break
                    except:
                        continue

            except Exception as e:
                print(f"Could not find likes: {e}")

            # Try to find image/video URLs
            try:
                # Find images
                img_elements = browser.find_elements(By.XPATH, "//img[contains(@src, 'instagram')]")
                for img in img_elements:
                    src = img.get_attribute('src')
                    if src and 'instagram' in src and src not in post_data['image_urls']:
                        post_data['image_urls'].append(src)

                # Find videos
                video_elements = browser.find_elements(By.XPATH, "//video")
                for video in video_elements:
                    src = video.get_attribute('src')
                    if src and src not in post_data['video_urls']:
                        post_data['video_urls'].append(src)

            except Exception as e:
                print(f"Could not find media URLs: {e}")

            return post_data

        except Exception as e:
            print(f"Error extracting post data: {e}")
            return None

def main():
    """Main function to run the post scraper"""
    target_user = 'galvekselman'  # Change this to scrape different users
    max_posts = 10  # Number of posts to scrape

    # Create scraper instance
    scraper = InstagramPostScraper(bot_username, bot_password)

    try:
        # Login to Instagram
        scraper.login()

        # Scrape posts
        posts = scraper.scrape_user_posts(target_user, max_posts)

        # Save to CSV
        if posts:
            csv_filename = f'{target_user}_posts.csv'
            with open(csv_filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['post_id', 'url', 'caption', 'likes', 'comments', 'timestamp', 'image_urls', 'video_urls']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for post in posts:
                    # Convert lists to strings for CSV
                    post_copy = post.copy()
                    post_copy['image_urls'] = ', '.join(post['image_urls'])
                    post_copy['video_urls'] = ', '.join(post['video_urls'])
                    writer.writerow(post_copy)

            print(f"Successfully saved {len(posts)} posts to {csv_filename}")

            # Also save as JSON for complete data
            json_filename = f'{target_user}_posts.json'
            with open(json_filename, 'w', encoding='utf-8') as jsonfile:
                json.dump(posts, jsonfile, indent=2, ensure_ascii=False)

            print(f"Also saved detailed data to {json_filename}")
        else:
            print("No posts were scraped")

    except Exception as e:
        print(f"Error during scraping: {e}")
    finally:
        # Clean up
        try:
            scraper.close_browser()
        except:
            pass

if __name__ == "__main__":
    main()