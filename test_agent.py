

import json
from math import ceil

def get_profile():
    with open('profile.json') as file:
        return json.load(file)


#get_profile()
missions =[]
max = 36
for k in range(max):
    missions.append(f"Mission {k}")
#print(missions)

def parcours_batch():
    """missions[0, 5]
    missions[5, 10]
    missions[10, 5]
    ...
    missions[35, 36]"""
    for i in range(0, len(missions), 5):
        batch = missions[ i: i+5]
        for mission in batch:
            print(mission)
    

parcours_batch()
