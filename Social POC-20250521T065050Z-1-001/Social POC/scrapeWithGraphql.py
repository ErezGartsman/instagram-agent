# -*- coding: utf-8 -*-
"""
Created on Tue Mar 16 13:29:25 2021

@author: User
"""

from selenium import webdriver
from bs4 import BeautifulSoup as bs
import time
import json
import pandas as pd

insta_account = 'lapicanteff'
insta_pass = 'Gv300444494!'
JS_SCROLL_SCRIPT = "window.scrollTo(0, document.body.scrollHeight); var lenOfPage=document.body.scrollHeight; return lenOfPage;"
username= 'galvekselman'#'cafenimrod'
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

source = browser.page_source
data=bs(source, 'html.parser')
body = data.find('body')
script = body.find('script', text=lambda t: t.startswith('window._sharedData'))
page_json = script.string.split(' = ', 1)[1].rstrip(';')
data = json.loads(page_json)

links = []
for link in data['entry_data']['ProfilePage'][0]['graphql']['user']['edge_owner_to_timeline_media']['edges']:
    links.append('https://www.instagram.com'+'/p/'+link['node']['shortcode']+'/')

last_page = data['entry_data']['ProfilePage'][0]['graphql']['user']['edge_owner_to_timeline_media']['page_info']['end_cursor']
has_next_page = data['entry_data']['ProfilePage'][0]['graphql']['user']['edge_owner_to_timeline_media']['page_info']['has_next_page']
user_id = data['entry_data']['ProfilePage'][0]['graphql']['user']['id']

if has_next_page == True:
    while has_next_page:
        browser.get('https://www.instagram.com/graphql/query/?query_hash=56a7068fea504063273cc2120ffd54f3&variables=%7B%22id%22%3A%22' + user_id + '%22%2C%22first%22%3A12%2C%22after%22%3A%22'+ last_page +'%22%7D')
        time.sleep(3)
        
        source = browser.page_source
        data=bs(source, 'html.parser')
        body = data.find('body').text
        data = json.loads(body)
        
        last_page = data['data']['user']['edge_owner_to_timeline_media']['page_info']['end_cursor']
        has_next_page = data['data']['user']['edge_owner_to_timeline_media']['page_info']['has_next_page']
        for link in data['data']['user']['edge_owner_to_timeline_media']['edges']:
            links.append('https://www.instagram.com'+'/p/'+link['node']['shortcode']+'/')

    
links = pd.DataFrame(links)
links['user'] = username
browser.close()

