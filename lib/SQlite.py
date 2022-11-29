# -*- coding: utf-8 -*-
"""
Created on Sat Dec  4 16:00:27 2021

@author: nonev
"""


from PySide6.QtCore import QObject, Signal, Slot, QTimer
import sqlite3
import datetime

class SQliteClient(QObject):
    status = Signal(int)
    message = Signal(str)
    stats = Signal(int)
    ERROR = -1
    LISTEN = 1
    CONNECTED = 2
    STOP = 3

    SIG_NORMAL = 0
    SIG_STOP = 1
    SIG_DISCONNECT = 2
    
    sql_create_packets_table = """ CREATE TABLE IF NOT EXISTS packets (
                                    timestamp REAL NOT NULL,
                                    sensor_id INTEGER,
                                    sequence_id INTEGER,
                                    data_format INTEGER,
                                    data_size INTEGER,
                                    data BLOB
                                    ); """

    # data type for meas start and meas stop?!?
    sql_create_measurements_table = """ CREATE TABLE IF NOT EXISTS measurements (
                                        measurement_id char (128) NOT NULL,
                                        comments char (128) NOT NULL,
                                        sensor_id INTEGER,
                                        meas_start INTEGER,
                                        meas_stop INTEGER,
                                        processed BOOL
                                        ); """
    
    
    sql_create_index = """ CREATE INDEX idx_time ON packets (timestamp) ; """


    def __init__(self, filename):
        QObject.__init__(self)

        self.filename = filename
        self.signal = self.SIG_NORMAL
        self.connection = sqlite3.connect(self.filename, check_same_thread=False)
        self.c = self.connection.cursor()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.periodicTimer)
        self.timer.start(100)
        self.packetCounter = 1
        self.measurementCounter = 1


    @Slot()
    def start(self):
        try:

            self.message.emit("Starting Message Provider")
            self.c.execute('pragma journal_mode=wal')
            self.c.execute('PRAGMA journal_mode = MEMORY')
            self.c.execute('PRAGMA synchronous = OFF')
            self.c.execute('PRAGMA auto_vacuum = 0')

            # Check for existing packets table
            self.c.execute(''' SELECT count(name) FROM sqlite_master WHERE type='table' AND name='packets' ''')
            self.message.emit("Checking Packets Table")

            if self.c.fetchone()[0] == 1:
                self.message.emit("Table Exists, ready to go")
            else:
                self.message.emit("Table not Found, creating it...")
                self.c.execute(self.sql_create_packets_table)
                self.connection.commit()
                self.c.execute(self.sql_create_index)
                self.connection.commit()
                self.message.emit("Done")

            # Check for existing measurements table
            self.c.execute(''' SELECT count(name) FROM sqlite_master WHERE type='table' AND name='measurements' ''')
            self.message.emit("Checking Measurements Table")

            if self.c.fetchone()[0] == 1:
                self.message.emit("Table Exists, ready to go")
            else:
                self.message.emit("Table not Found, creating it...")
                self.c.execute(self.sql_create_measurements_table)
                self.connection.commit()
                self.message.emit("Done")

        except OSError as err:
            self.status.emit(self.STOP)

        else:
            self.status.emit(self.CONNECTED)
            '''
            while True:
                
            
              
                if self.signal == self.SIG_NORMAL:
                    
                    pass
                elif self.signal == self.SIG_STOP:
                    self.signal = self.SIG_NORMAL
                    
                    
                    break
                
        finally:
            self.status.emit(self.STOP)'''
    @Slot()
    def insertPackets(self, values):
        self.packetCounter += 1
        # with self.connection:
        self.c.execute('insert into packets values (?,?,?,?,?,?)', (values['timestamp'], values['sensor_id'],
                                                                    values['sequence_id'], values['data_format'],
                                                                    values['data_size'], values['data']))
        self.connection.commit()

    @Slot()
    def insertMeasurements(self, values):
        self.measurementCounter += 1
        # with self.connection:
        self.c.execute('insert into measurements values (?,?,?,?,?,?)', (values['measurement_id'], values['comments'],
                                                                         values['sensor_id'], values['meas_start'],
                                                                         values['meas_stop'], values['processed']))
        self.connection.commit()
        
        
        
    def checkMeasurement(self, measurement_id):
        self.c.execute("SELECT rowid FROM measurements WHERE measurement_id = ?", (measurement_id,))
        
        data=self.c.fetchall()
        if len(data)==0:
            return 1
        else:
            return 0

    @Slot()
    def getPacket(self, radar_id, timespan):
        # get data from database
        now = datetime.datetime.timestamp(datetime.datetime.now())
        old = now-timespan
        
        sensor_data = self.c.execute('SELECT * FROM packets WHERE timestamp between ? and ? and sensor_id = ? limit 1000',(old,now,radar_id ))   
        data = sensor_data.fetchall()
        #print(data)
        return data
    
    
    def getRadStat(self, radar_id):
        # get data from database
        now = datetime.datetime.timestamp(datetime.datetime.now())
        old = now-1
        
        sensor_data = self.c.execute('SELECT count() FROM packets WHERE timestamp between ? and ? and sensor_id = ?',(old,now,radar_id ))   
        data = sensor_data.fetchone()[0]
        #print(data)
        return data

    def close(self):
        print(self.connection)
        self.connection.commit()
        self.connection.close()

        self.status.emit(self.STOP)
        self.timer.stop()
        self.thread().quit()

    def periodicTimer(self):
        
        #self.connection.commit()
        self.stats.emit(self.packetCounter*10)
        self.packetCounter = 0
        self.timer.stop()
        self.timer.start(100)

        
