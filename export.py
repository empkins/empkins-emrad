

import sys
from pathlib import Path
import json
import sqlite3
import numpy as np
import h5py
from slugify import slugify


from lib.pparser import emRadParser











config_file = Path('config.json')

if config_file.exists():
    config = json.load(open('config.json', 'r'))
else:
    config = dict()
    json.dump(config, open('config.json', 'w+'))
    
if not config.get('DBFilename'):
    print("Error: DBFile not Configured")
    sys.exit()

db_file = Path(config.get('DBFilename'))
print (config.get('DBFilename'))
if not db_file.exists():
    print("Error: DBFile not Found")
    sys.exit()



parser = emRadParser()

connection = sqlite3.connect(config.get('DBFilename'), check_same_thread=False)
c = connection.cursor()
        
 
    
 
    
c.execute("SELECT rowid, * FROM measurements WHERE processed = 0")
rows = c.fetchall()





for row in rows:
    rowid = row[0]
    measurement_id = row[1]
    comment = row[2]
    sensor_id = int(row[3])
    start  = row[4]
    stop = row[5]
    
    
    print("Got Measurement ID:" ,  measurement_id)
    
    c.execute("SELECT * FROM packets WHERE sensor_id = ? and timestamp BETWEEN ? and ?", (sensor_id, start, stop))
    packets = c.fetchall()
    series = []
    for packet in packets:
        series.append(parser.parse(packet[8]))
    try:     
        series = np.concatenate(series)
    except:
        series = np.array([])

    filename = "data_" + slugify(measurement_id) + ".h5"
    path = Path(filename)
    
    if path.exists():
        print("File already exist, export Skipped")
    else:
        
        hf = h5py.File(filename, 'w')
        g = hf.create_group('Radar')
        g.attrs["measurement_id"] = measurement_id
        g.attrs["comment"] = comment
        g.attrs["sensor_id"] = sensor_id
        g.attrs["start"] = start
        g.attrs["stop"] = stop
        
        print(np.shape(series))
        g.create_dataset('rad1', data=series[:,[0,1,8,9]] )
        g.create_dataset('rad2', data=series[:,[2,3,8,9]] )
        g.create_dataset('rad3', data=series[:,[4,5,8,9]] )
        g.create_dataset('rad4', data=series[:,[6,7,8,9]] )
    
        hf.close()
        c.execute("UPDATE measurements SET processed = 1 WHERE rowid = ?", (rowid,))
        connection.commit()
        

connection.close()