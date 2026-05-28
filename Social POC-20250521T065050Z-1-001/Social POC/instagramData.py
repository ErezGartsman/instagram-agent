# -*- coding: utf-8 -*-
"""
Created on Thu Mar 18 03:50:39 2021

@author: User
"""

import instaloader
import pandas as pd

#------------------------------------------------
#Login
L = instaloader.Instaloader() 
L.login('lapicanteff', 'Gv300444494!')        # (login)




#------------------------------------------------
#Get profile to scrape
username = 'kobi_yosov' #'cafenimrod'
profile = instaloader.Profile.from_username(L.context, username) 

#------------------------------------------------
#Get all posts
post_list = pd.DataFrame(columns=['username',
                                  'shortcode',
                                  'locationName',
                                  'locationlat',
                                  'locationlng',
                                  'likes',
                                  'comments',
                                  'url',
                                  'date_local',
                                  'date_utc'])
likee_list = pd.DataFrame(columns=['username',
                                   'shortcode',
                                   'likeeName'
                                   #'profile_pic',
                                   #'profile_private'
                                   ])
for post in profile.get_posts():    
    if post.location is not None:
        locationName = post.location.name
        locationLat = post.location.lat
        locationLng = post.location.lng
    else:
        locationName = None
        locationLat = None
        locationLng = None
    
    post_list = post_list.append({'username': username,
                    'shortcode': post.shortcode,
                    'locationName': locationName,
                    'locationlat': locationLat,
                    'locationlng': locationLng,
                    'likes': post.likes,
                    'comments': post.comments,
                    'url': post.url,
                    'date_local': post.date_local,
                    'date_utc': post.date_utc
                    }
                   , ignore_index=True)
    
#------------------------------------------------  
#Get all people that likes my post 
    post_likes = post.get_likes()
    for likee in post_likes:
        try:
            print(likee)
            likee_list = likee_list.append({'username': username,
                        'shortcode': post.shortcode,
                        'likeeName': likee.username,
                        'followees': likee.followees,
                        'followers': likee.followers,
                        'is_private': likee.is_private,
                        'is_business_account': likee.is_business_account,
                        'profile_pic': instaloader.Profile.from_username(L.context, likee.username).profile_pic_url,
                        'profile_private': instaloader.Profile.from_username(L.context, likee.username).is_private,
                        }
                       , ignore_index=True)
        except:
            pass
        
#------------------------------------------------
# likee_list = likee_list[['username','likeeName']]
# likee_list = likee_list.drop_duplicates()
# likee_list['profile_pic'] = likee_list.apply(lambda x: instaloader.Profile.from_username(L.context, x['username']).profile_pic_url, axis=1)
# likee_list['profile_private'] = likee_list.apply(lambda x: instaloader.Profile.from_username(L.context, x['username']).is_private, axis=1)
