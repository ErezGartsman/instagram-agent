# -*- coding: utf-8 -*-
"""
Created on Sat Oct 16 13:31:44 2021
@project: Instagram Places Scraping
@author: Gal Vekselman
"""

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
import time, random
from bs4 import BeautifulSoup as bs
import time
import json
import pandas as pd

#Username and password config
my_username = 'lapicanteff'
my_password = 'Gv300444494!'
places = ['417541267','214155187','5438','216663669']


browser = webdriver.Chrome('G:/My Drive/Corvex Dental/chromedriver.exe')


#Authorazation
def auth(username,passwors):
    try:
        browser.get('https://instagram.com')
        time.sleep(random.randrange(2,4))
        username_el = browser.find_element_by_name('username')
        password_el = browser.find_element_by_name('password')
        
        username_el.send_keys(my_username)
        time.sleep(random.randrange(1,2))
        password_el.send_keys(my_password)
        time.sleep(random.randrange(1,2))
        
        submit_btn_el = browser.find_element_by_css_selector("button[type='submit']")
        submit_btn_el.click()
        
        
    except Exception as err:
        print(err)
        browser.quit()
        
        
def get_places_page(places):
    users = pd.DataFrame(columns=('Place','PostCode','PostLink','FullName','UserName','ProfilePic','CommercialityStatus','DeviceTimestamp'))
    for place in places:
        browser.get('https://www.instagram.com/explore/locations/' + place)
        source = browser.page_source
        data=bs(source, 'html.parser')
        body = data.find('body')
        script = body.find('script', text=lambda t: t.startswith('window._sharedData'))
        page_json = script.string.split(' = ', 1)[1].rstrip(';')
        data = json.loads(page_json)
        
        recent = data['entry_data']['LocationsPage'][0]['native_location_data']['recent']['sections']
        
        for index in range(len(recent)):
            for index2 in range(len(recent[index]['layout_content']['medias'])):
                PostCode = recent[index]['layout_content']['medias'][index2]['media']['code']
                PostLink = 'https://www.instagram.com/p/'+ recent[index]['layout_content']['medias'][index2]['media']['code']
                FullName = recent[index]['layout_content']['medias'][index2]['media']['user']['full_name']
                UserName = recent[index]['layout_content']['medias'][index2]['media']['user']['username']
                ProfilePic = recent[index]['layout_content']['medias'][index2]['media']['user']['profile_pic_url']
                CommercialityStatus = recent[index]['layout_content']['medias'][index2]['media']['commerciality_status']
                DeviceTimestamp = recent[index]['layout_content']['medias'][index2]['media']['device_timestamp']
                
                df = pd.DataFrame([(place,PostCode,PostLink,FullName,UserName,ProfilePic,CommercialityStatus,DeviceTimestamp)],columns=('Place','PostCode','PostLink','FullName','UserName','ProfilePic','CommercialityStatus','DeviceTimestamp'))
                users = users.append(df, ignore_index=True)
    browser.quit()        
    return users
        
auth(my_username,my_password)  
time.sleep(random.randrange(3,4))
aa = get_places_page(places)



