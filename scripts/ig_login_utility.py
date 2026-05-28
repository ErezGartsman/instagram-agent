from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# פתיחת פרופיל הכרום של הסקריפט שלנו
opts = Options()
opts.add_argument(r"--user-data-dir=C:\Users\Erez\SeleniumProfile")
opts.add_argument(r"--profile-directory=Default")

driver = webdriver.Chrome(options=opts)
driver.get("https://www.instagram.com/accounts/login/")

# עוצר את הטרמינל ומחכה שתתחבר
input("Press Enter here in the terminal ONLY AFTER you successfully logged in to Instagram in the browser...")

driver.quit()