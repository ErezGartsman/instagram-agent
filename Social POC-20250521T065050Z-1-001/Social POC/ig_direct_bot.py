# -*- coding: utf-8 -*-
"""
Created on Sat Oct 16 13:31:44 2021
@project: Instagram
@author: Gal Vekselman
"""

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
import time, random

#Username and password config
my_username = 'lapicanteff'
my_password = 'Gv300444494!'

#Usernames for DM
usernames = ['galvekselman']

#Random messages
messages = ['Hey, please follow me','Hello','Hey']

#Delay between messages
between_messages = 5

browser = webdriver.Chrome('G:/My Drive/Corvex Dental/instagram/chromedriver.exe')

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
        time.sleep(random.randrange(1,3))
        
    except Exception as err:
        print(err)
        browser.quit()
 
#Sending the message
def send_message(users,message):
    try:
        browser.find_element_by_xpath('//*[@id="react-root"]/section/nav/div[2]/div/div/div[3]/div/div[2]/a').click()
        time.sleep(random.randrange(3,5))
        browser.find_element_by_xpath('/html/body/div[6]/div/div/div/div[3]/button[2]').click()
        time.sleep(random.randrange(1,2))
        browser.find_element_by_xpath('//*[@id="react-root"]/section/div/div[2]/div/div/div[2]/div/div[3]/div').click()
        for user in users:
            time.sleep(random.randrange(1,2))
            browser.find_element_by_xpath('/html/body/div[6]/div/div/div[2]/div[1]/div/div[2]/input').send_keys(user)
            time.sleep(random.randrange(2,3))
            browser.find_element_by_xpath('/html/body/div[6]/div/div/div[2]/div[2]').find_element_by_tag_name('button').click()
            time.sleep(random.randrange(3,4))
            browser.find_element_by_xpath('/html/body/div[6]/div/div/div[1]/div/div[2]/div/button/div').click()
            time.sleep(random.randrange(3,4))
            text_area = browser.find_element_by_xpath('/html/body/div[1]/section/div/div[2]/div/div/div[2]/div[2]/div/div[2]/div/div/div[2]/textarea')
            text_area.send_keys(random.choice(messages))
            time.sleep(random.randrange(2,4))
            text_area.send_keys(Keys.ENTER)
            print(f'send to {user}')
            time.sleep(between_messages)
            browser.find_element_by_xpath('//*[@id="react-root"]/section/div/div[2]/div/div/div[1]/div[1]/div/div[3]/button').click()
            
    except Exception as err:
        print(err)
        browser.quit()
        
        
def follow_user(username):
    try:   
        browser.get('https://www.instagram.com/' + username)
        time.sleep(random.randrange(3,5))
        browser.find_element_by_xpath('/html/body/div[1]/section/main/div/header/section/div[1]/div[1]/div/div').click()
       
    
    except Exception as err:
        print(err)
        browser.quit()



auth(my_username,my_password)
time.sleep(random.randrange(3,4))
send_message(usernames,messages)