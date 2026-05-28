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
bot_username = 'erez_gersman'
bot_password = 'ErAgK1899($)'

class InstagramPostAndLikersScraper:
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

    def scrape_post_likers(self, post_url):
        """Scrape all users who liked a specific post"""
        browser = self.browser
        wait = WebDriverWait(browser, 15)

        try:
            print(f"Scraping likers for: {post_url}")
            browser.get(post_url)
            time.sleep(random.randrange(3, 5))

            # Find and click the likes count to open likers modal
            likes_selectors = [
                "//button[contains(@class, '_abl-')]//span[contains(text(), 'likes')]",
                "//button[contains(text(), 'likes')]",
                "//span[contains(text(), 'likes')]/ancestor::button[1]",
                "//a[contains(@href, '/liked_by/')]",
                "//*[contains(text(), 'likes') and (@role='button' or ancestor::button)]"
            ]

            likes_button = None
            for selector in likes_selectors:
                try:
                    likes_button = wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                    print(f"Found likes button with selector: {selector}")
                    break
                except:
                    continue

            if not likes_button:
                print("Could not find likes button")
                return []

            # Scroll to make the element visible and click
            try:
                # Scroll the element into view
                browser.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", likes_button)
                time.sleep(1)

                # Try multiple click methods
                click_success = False

                # Method 1: Regular click
                try:
                    likes_button.click()
                    click_success = True
                    print("Successfully clicked likes button (regular click)")
                except:
                    pass

                # Method 2: JavaScript click
                if not click_success:
                    try:
                        browser.execute_script("arguments[0].click();", likes_button)
                        click_success = True
                        print("Successfully clicked likes button (JavaScript click)")
                    except:
                        pass

                # Method 3: Action chains
                if not click_success:
                    try:
                        from selenium.webdriver.common.action_chains import ActionChains
                        actions = ActionChains(browser)
                        actions.move_to_element(likes_button).click().perform()
                        click_success = True
                        print("Successfully clicked likes button (Action chains)")
                    except:
                        pass

                if not click_success:
                    print("Could not click likes button with any method")
                    return []

            except Exception as e:
                print(f"Error clicking likes button: {e}")
                return []

            time.sleep(random.randrange(3, 5))

            # Wait for likers modal to load
            likers_modal = None
            modal_selectors = [
                "//div[@role='dialog']",
                "//div[contains(@style, 'overflow')]",
                "//div[contains(@class, '_aano')]"
            ]

            for modal_selector in modal_selectors:
                try:
                    likers_modal = wait.until(EC.presence_of_element_located((By.XPATH, modal_selector)))
                    print(f"Found likers modal with selector: {modal_selector}")

                    # Check if it contains user links
                    test_users = likers_modal.find_elements(By.XPATH, ".//a[contains(@href, '/')]")
                    if len(test_users) > 0:
                        print(f"Modal contains {len(test_users)} user links")
                        break
                except:
                    continue

            if not likers_modal:
                print("Could not find likers modal")
                return []

            # Scroll through the modal to get ALL likers
            likers = set()
            scroll_attempts = 0
            max_attempts = 100  # Increased for posts with many likes
            consecutive_no_new = 0
            max_no_new_attempts = 15  # More patient before giving up

            print("Starting likers collection...")

            while scroll_attempts < max_attempts and consecutive_no_new < max_no_new_attempts:
                # Find all user links in modal
                user_links = likers_modal.find_elements(By.XPATH, ".//a[contains(@href, '/') and not(contains(@href, '/p/')) and not(contains(@href, '/reel/'))]")

                before_count = len(likers)

                for link in user_links:
                    try:
                        href = link.get_attribute('href')
                        if href and 'instagram.com/' in href:
                            username = href.replace('https://www.instagram.com/', '').replace('/', '').strip()
                            if username and len(username) > 0 and not any(x in username for x in ['explore', 'accounts', 'p', 'reel', 'tv']):
                                likers.add(username)
                    except:
                        continue

                new_count = len(likers) - before_count
                if new_count > 0:
                    print(f"Found {new_count} new likers, total: {len(likers)}")
                    consecutive_no_new = 0  # Reset counter when we find new likers
                else:
                    consecutive_no_new += 1

                # Multiple scrolling strategies to ensure we reach the bottom
                scroll_attempts += 1

                if scroll_attempts % 3 == 1:
                    # Method 1: Scroll by pixels
                    browser.execute_script("arguments[0].scrollTop += 400", likers_modal)
                elif scroll_attempts % 3 == 2:
                    # Method 2: Scroll to bottom
                    browser.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", likers_modal)
                else:
                    # Method 3: Scroll to last visible element
                    if user_links:
                        browser.execute_script("arguments[0].scrollIntoView(false);", user_links[-1])

                # Longer wait to allow content to load
                time.sleep(random.randrange(2, 4))

                # Progress update every 10 attempts
                if scroll_attempts % 10 == 0:
                    print(f"Progress: {scroll_attempts} scrolls, {len(likers)} likers found, {consecutive_no_new} consecutive empty scrolls")

            print(f"Finished collecting likers. Total: {len(likers)} (after {scroll_attempts} scroll attempts)")

            # Close the modal by pressing Escape or clicking close button
            try:
                browser.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
                time.sleep(1)
            except:
                pass

            return list(likers)

        except Exception as e:
            print(f"Error scraping likers for {post_url}: {e}")
            return []

    def scrape_user_posts_with_likers(self, target_username, max_posts=5):
        """Scrape posts and their likers from a specific user's profile"""
        browser = self.browser
        wait = WebDriverWait(browser, 15)

        print(f"Scraping posts and likers from @{target_username}...")

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
            # Find post links on the profile
            post_links = []
            scroll_attempts = 0
            max_scroll_attempts = 10

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

                print(f"Found {len(post_links)} post links so far...")

                # Scroll down to load more posts
                browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.randrange(2, 4))

                if len(post_links) >= max_posts:
                    break

                scroll_attempts += 1

            print(f"Found {len(post_links)} total post links")

            # Limit to requested number
            post_links = post_links[:max_posts]

            # Now visit each post to get details AND likers
            for i, post_url in enumerate(post_links):
                try:
                    print(f"\n=== Processing post {i+1}/{len(post_links)} ===")
                    print(f"Post URL: {post_url}")

                    # Get basic post data
                    browser.get(post_url)
                    time.sleep(random.randrange(2, 4))

                    post_data = self.extract_post_data(post_url)
                    if not post_data:
                        continue

                    # Get likers for this post
                    likers = self.scrape_post_likers(post_url)
                    post_data['likers'] = likers
                    post_data['likers_count'] = len(likers)

                    posts_data.append(post_data)

                    print(f"Post {i+1} complete: {len(likers)} likers collected")

                    # Add delay between posts
                    time.sleep(random.randrange(2, 4))

                except Exception as e:
                    print(f"Error processing post {post_url}: {e}")
                    continue

        except Exception as e:
            print(f"Error during post collection: {e}")

        return posts_data

    def extract_post_data(self, post_url):
        """Extract basic data from individual post page"""
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

            return post_data

        except Exception as e:
            print(f"Error extracting post data: {e}")
            return None

def main():
    """Main function to run the enhanced post and likers scraper"""
    target_user = 'erez_gersman'  # Change this to scrape different users
    max_posts = 3  # Reduced for testing (likers scraping takes time)

    # Create scraper instance
    scraper = InstagramPostAndLikersScraper(bot_username, bot_password)

    try:
        # Login to Instagram
        scraper.login()

        # Scrape posts with likers
        posts = scraper.scrape_user_posts_with_likers(target_user, max_posts)

        if posts:
            # Save posts data to CSV
            posts_csv = f'{target_user}_posts_with_likers.csv'
            with open(posts_csv, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['post_id', 'url', 'caption', 'likes', 'comments', 'timestamp', 'image_urls', 'video_urls', 'likers_count']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for post in posts:
                    # Create a clean copy excluding likers list
                    post_copy = {k: v for k, v in post.items() if k != 'likers'}
                    # Convert lists to strings for CSV
                    if 'image_urls' in post_copy:
                        post_copy['image_urls'] = ', '.join(post_copy.get('image_urls', []))
                    if 'video_urls' in post_copy:
                        post_copy['video_urls'] = ', '.join(post_copy.get('video_urls', []))
                    writer.writerow(post_copy)

            print(f"Saved posts data to {posts_csv}")

            # Save likers data to separate CSV
            likers_csv = f'{target_user}_likers.csv'
            with open(likers_csv, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['post_id', 'post_url', 'liker_username']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for post in posts:
                    for liker in post.get('likers', []):
                        writer.writerow({
                            'post_id': post.get('post_id', ''),
                            'post_url': post.get('url', ''),
                            'liker_username': liker
                        })

            print(f"Saved likers data to {likers_csv}")

            # Save complete data as JSON
            json_filename = f'{target_user}_posts_and_likers.json'
            with open(json_filename, 'w', encoding='utf-8') as jsonfile:
                json.dump(posts, jsonfile, indent=2, ensure_ascii=False)

            print(f"Saved complete data to {json_filename}")

            # Print summary
            total_likers = sum(len(post.get('likers', [])) for post in posts)
            print(f"\n=== SUMMARY ===")
            print(f"Posts scraped: {len(posts)}")
            print(f"Total unique likers collected: {total_likers}")
            for i, post in enumerate(posts):
                print(f"Post {i+1}: {len(post.get('likers', []))} likers")

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