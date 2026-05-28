# -*- coding: utf-8 -*-
"""
Created on Tue Mar 16 13:29:25 2021
Moonlight sonata
@author: User
"""

from selenium import webdriver
from bs4 import BeautifulSoup as bs
import time
import json
import pandas as pd
from explicit import waiter, XPATH
import itertools

insta_account = 'erez_gersman'
insta_pass = 'ErAgK1899!!E'
JS_SCROLL_SCRIPT = "window.scrollTo(0, document.body.scrollHeight); var lenOfPage=document.body.scrollHeight; return lenOfPage;"
username= 'likudnik'#'cafenimrod'
browser = webdriver.Chrome('I:/My Drive/Corvex Dental/instagram/chromedriver.exe')



url = 'https://www.instagram.com'
browser.get(url)
time.sleep(2)

username_el = browser.find_element_by_name('username')
username_el.send_keys(insta_account)

password_el = browser.find_element_by_name('password')
password_el.send_keys(insta_pass)
time.sleep(2)

submit_btn_el = browser.find_element_by_css_selector("button[type='submit']")
submit_btn_el.click()
time.sleep(10)




browser.get('https://www.instagram.com/'+username+'/?hl=en')
time.sleep(5)

browser.find_element_by_partial_link_text("follower").click()
# Wait for the followers modal to load
waiter.find_element(browser, "//div[@role='dialog']", by=XPATH)
allfoll = 602 #int(browser.find_element_by_xpath("/html/body/div[1]/div/div/div/div[1]/div/div/div/div[1]/div[1]/section/main/div/ul/li[2]/a/div").text)
# At this point a Followers modal pops open. If you immediately scroll to the bottom,
# you hit a stopping point and a "See All Suggestions" link. If you fiddle with the
# model by scrolling up and down, you can force it to load additional followers for
# that person.

# Now the modal will begin loading followers every time you scroll to the bottom.
# Keep scrolling in a loop until you've hit the desired number of followers.
# In this instance, I'm using a generator to return followers one-by-one
follower_css = "ul div li:nth-child({}) a.notranslate" 



for group in itertools.count(start=1, step=12):
    for follower_index in range(group, group + 11):
        if follower_index > allfoll:
            raise StopIteration
        print(waiter.find_element(browser, follower_css.format(follower_index)).text)

    # Instagram loads followers 12 at a time. Find the last follower element
    # and scroll it into view, forcing instagram to load another 12
    # Even though we just found this elem in the previous for loop, there can
    # potentially be large amount of time between that call and this one,
    # and the element might have gone stale. Lets just re-acquire it to avoid
    # tha
    
    last_follower = waiter.find_element(browser, follower_css.format(group+11))
    browser.execute_script("arguments[0].scrollIntoView();", last_follower)
    
#browser.close()

