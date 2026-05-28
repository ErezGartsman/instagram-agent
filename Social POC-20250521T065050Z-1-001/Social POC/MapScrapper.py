# -*- coding: utf-8 -*-
"""
Created on Thu Mar 11 04:39:23 2021

@author: User
"""

import googlemaps
import pprint
import time
import pandas as pd
from bs4 import BeautifulSoup
from urllib.request import Request, urlopen, HTTPError

#define clients
api = 'AIzaSyCL_uoqnNaSn93e6qSG8IhhtMAtEBWAST0'
gmaps = googlemaps.Client(key = api)


def get_all_socials_from_website(website):
    try:
        
        #req = Request("https://www.clinicatorrescarranza.es/")
        req = Request(website)
        html_page = urlopen(req)
        
        soup = BeautifulSoup(html_page, "lxml")
        
        links = []
        for link in soup.findAll('a'):
            links.append(link.get('href'))
        
        links = pd.DataFrame(links)
        searchfor = ['facebook', 'linkedin.com/company','twitter','youtube','whatsapp','instagram']
        links = links[links[0].str.contains('|'.join(searchfor))].dropna()
        links = links[~links[0].str.contains("%")]
        links = links.drop_duplicates(subset=[0])
        links = links.rename(columns={0: 'Link'})
        
        def get_my_social(txt):
            if txt.find('facebook') > 0:
                social = 'facebook'
            elif txt.find('twitter') > 0:
                social = 'twitter'
            elif txt.find('instagram') > 0:
                social = 'instagram'
            elif txt.find('linkedin') > 0:
                social = 'linkedin'
            elif txt.find('youtube') > 0:
                social = 'youtube'
            elif txt.find('whatsapp') > 0:
                social = 'whatsapp'
            else:
                social = ''
            return social
        
        links['Social'] = links.apply(lambda x: get_my_social(x['Link']), axis=1)
        
    except:
        links = pd.DataFrame({'Link': ['ERROR'], 'Social': ['No access']})
    return links


def map_data(location):

    #scrape initial data
    appended_data = []
    places_results = gmaps.places_nearby(location= location, #'32.07475052084715, 34.77052029638048',
                                         radius=1000,
                                         open_now=False,
                                         type='cafe')
    
    df = pd.DataFrame(places_results['results'])
    df_all = df[['place_id','name','vicinity','user_ratings_total','rating']]
    geo_lst = list(pd.DataFrame(places_results['results'])['geometry'].to_dict().values())
    geo_df = pd.DataFrame(list(pd.DataFrame(geo_lst)['location'].to_dict().values()))
    df_all = df_all.join(geo_df, lsuffix='_main', rsuffix='_other')
    appended_data.append(df_all)
    
    
    
    
    #loop throw next pageg
    if 'next_page_token' in places_results.keys():
        while True:  
            time.sleep(2)
            places_results = gmaps.places_nearby(page_token = places_results['next_page_token']) 
            df = pd.DataFrame(places_results['results'])
            df_all = df[['place_id','name','vicinity','user_ratings_total','rating']]
            geo_lst = list(pd.DataFrame(places_results['results'])['geometry'].to_dict().values())
            geo_df = pd.DataFrame(list(pd.DataFrame(geo_lst)['location'].to_dict().values()))
            df_all = df_all.join(geo_df, lsuffix='_main', rsuffix='_other')
            appended_data.append(df_all)
            if(not('next_page_token' in places_results.keys())):  
                break  
    else:
        pass
    
    results_pd = pd.concat(appended_data).reset_index()
    results_pd = results_pd.drop(['index'], axis=1)
    
    
    #scrape locations details
    appended_data = []
    for index, row  in results_pd.iterrows():
        my_place_id = results_pd['place_id'][index]
        my_fields = ['name','formatted_phone_number','website']
        place_details = gmaps.place(place_id = my_place_id, fields = my_fields)['result']
        place_details['place_id'] = results_pd['place_id'][index]
        appended_data.append(place_details)
        
    
    df_details = pd.DataFrame(appended_data)
    
    df_join = results_pd.join(df_details, lsuffix='_main', rsuffix='_other')
    #print(df_join)
    df_join = df_join[['place_id_main','name_main','vicinity','user_ratings_total','rating','formatted_phone_number','website','lat','lng']]
    df_join = df_join.rename(columns={"place_id_main": "place_id","name_main": "name"})

    return df_join

#loop location in area
locations = {
             'Location': ['32.09745164170756, 34.77353355659131'
                        
                        ]
             }
locations_df = pd.DataFrame(data=locations)


appended_data = []
for index, row in locations_df.iterrows():
    df = map_data(locations_df['Location'][index])
    appended_data.append(df)
 
#get table of locations
appended_data = pd.concat(appended_data) 
appended_data.drop_duplicates(subset=['place_id'])
appended_data.set_index(['place_id'], inplace = True, 
                    append = True, drop = True) 
appended_data.reset_index(inplace = True)
appended_data = appended_data.drop(['level_0'], axis=1)


#get socials of websites
websites = appended_data[['place_id','website']].dropna()
socials = []
for index, row in websites.iterrows():
    df = get_all_socials_from_website(websites['website'][index])
    df['place_id'] =websites['place_id'][index]
    socials.append(df)
    
socials = pd.concat(socials)
socials = socials[socials['Link'] != 'ERROR']