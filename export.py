

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
    

    
    series0 = []
    series1 = []
    series2 = []
    series3 = []

    c.execute("SELECT * FROM packets WHERE sensor_id = ? and timestamp BETWEEN ? and ?", (sensor_id*4, start, stop))
    packets = c.fetchall()

    for packet in packets:
        series0.append(parser.parse(packet[5]))
    try:     
        series0 = np.concatenate(series0)
    except:
        series0 = np.array([])
    
    c.execute("SELECT * FROM packets WHERE sensor_id = ? and timestamp BETWEEN ? and ?", (sensor_id*4+1, start, stop))
    packets = c.fetchall()

    for packet in packets:
        series1.append(parser.parse(packet[5]))
    try:     
        series1 = np.concatenate(series1)
    except:
        series1 = np.array([])
        
        
        
    c.execute("SELECT * FROM packets WHERE sensor_id = ? and timestamp BETWEEN ? and ?", (sensor_id*4+2, start, stop))
    packets = c.fetchall()

    for packet in packets:
        series2.append(parser.parse(packet[5]))
    try:     
        series2 = np.concatenate(series2)
    except:
        series2 = np.array([])
    
    
    c.execute("SELECT * FROM packets WHERE sensor_id = ? and timestamp BETWEEN ? and ?", (sensor_id*4+3, start, stop))
    packets = c.fetchall()

    for packet in packets:
        series3.append(parser.parse(packet[5]))
    try:     
        series3 = np.concatenate(series3)
    except:
        series3 = np.array([])
    
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

        g.create_dataset('rad1', data=series0)
        g.create_dataset('rad2', data=series1)
        g.create_dataset('rad3', data=series2)
        g.create_dataset('rad4', data=series3)
        hf.close()
        c.execute("UPDATE measurements SET processed = 1 WHERE rowid = ?", (rowid,))
        connection.commit()
        

connection.close()