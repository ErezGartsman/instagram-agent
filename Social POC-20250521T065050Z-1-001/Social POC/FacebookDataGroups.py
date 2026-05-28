# -*- coding: utf-8 -*-
"""
Created on Sat Nov 13 11:22:19 2021

@author: User
"""

from selenium import webdriver
from bs4 import BeautifulSoup as bs
import time, random
import json
import pandas as pd


#code by pythonjar, not me
chrome_options = webdriver.ChromeOptions()
prefs = {"profile.default_content_setting_values.notifications" : 2}
chrome_options.add_experimental_option("prefs",prefs)


account = 'gal@corvexanalytics.com'
fpass = 'Gv300444494'
JS_SCROLL_SCRIPT = "window.scrollTo(0, document.body.scrollHeight); var lenOfPage=document.body.scrollHeight; return lenOfPage;"
username='cafenimrod'
browser = webdriver.Chrome('G:/My Drive/Corvex Dental/instagram/chromedriver.exe',chrome_options=chrome_options)

url = 'https://www.facebook.com/login/?privacy_mutation_token=eyJ0eXBlIjowLCJjcmVhdGlvbl90aW1lIjoxNjM2ODIwNjQ5LCJjYWxsc2l0ZV9pZCI6MjY5NTQ4NDUzMDcyMDk1MX0%3D'
browser.get(url)
time.sleep(2)

username_el = browser.find_element_by_name('email')
username_el.send_keys(account)

password_el = browser.find_element_by_name('pass')
password_el.send_keys(fpass)
time.sleep(random.randrange(1,2))

submit_btn_el = browser.find_element_by_css_selector("button[type='submit']")
submit_btn_el.click()
time.sleep(random.randrange(1,2))


browser.get('https://www.facebook.com/groups/hotels.israel/members')
time.sleep(random.randrange(1,2))



for j in range(0,3):
    browser.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(random.randrange(3,7))

    anchors = browser.find_elements_by_tag_name('a')
    anchors_href = [a.get_attribute('href') for a in anchors]
    anchors_name = [a.text for a in anchors]
   # print(anchors.text)
browser.quit()
    
group_member_df = pd.DataFrame(
 {'href': anchors_href,
  'user_name': anchors_name,
 })
   
group_member_df = group_member_df[group_member_df['user_name']!='']
group_member_df['num'] = group_member_df['href'].str.find('user/') + 5
group_member_df = group_member_df[group_member_df['num']==54]
group_member_df['user_id'] = group_member_df['href'].str[54:]
group_member_df['user_id'] = group_member_df['href'].str[54:]
group_member_df['user_id'] = group_member_df['user_id'].str.replace('/','')
