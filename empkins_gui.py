"""
EmpkinS GUI to display data from EmpkinS Radar Sensors and define measurements

Define measurements:
    - Meta data: measurement ID, comments
    - Measurement data: start, stop

"""
import sqlite3
import sys
import time
from pathlib import Path

import PyQt5
from PyQt5 import QtCore, QtGui, uic, QtWidgets
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtCore import QTime
from qt_material import apply_stylesheet
from PySide6.QtCore import QThread, QFile
from threading import Lock
import pyqtgraph
import numpy as np
import datetime
import json
import scipy.signal

from lib.pparser import emRadParser
from lib.SQlite import SQliteClient



if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
   PyQt5.QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)

if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
    PyQt5.QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

# Define threading lock globally
lock = Lock()

# Constants

windowSize = 80
RadarRawInput = []

MINBPM = 50
MAXBPM = 130
MINBRPM = 3
MAXBRPM = 12
FS = round(8e6 / 1024 / 4)






class TemporalFilters():
        #Funktionen Filter
    def butter_bandpass_coeff(self,lowcut, highcut, fs, order=5):
        nyq = 0.5 * fs
        low = lowcut / nyq
        high = highcut / nyq
        sos = scipy.signal.butter(order, [low, high], btype='band', analog = False, output='sos')
        return sos
    
    def butter_lowpass_coeff(self,cutOff, fs, order=5):
       
        sos = scipy.signal.butter(order, cutOff, btype='lowpass', analog = False, output='sos', fs=fs)
        return sos
 
    def butter_highpass_coeff(self,cutOff, fs, order=5):
       
        sos = scipy.signal.butter(order, cutOff, btype='highpass', analog = False, output='sos', fs=fs)
        return sos
    
    
    def butter_bandpass_filter(self,data, lowcut, highcut, fs, order=5, zi=None):
        sos = self.butter_bandpass_coeff(lowcut, highcut, fs, order=order)
        #y = filtfilt(b, a, data)
        y = scipy.signal.sosfiltfilt(sos, data)
        return y    
    
    
    def butter_lowpass_filter(self,data, cutOff, fs, order=4, zi=None):
        sos = self.butter_lowpass_coeff(cutOff, fs, order=order)
        #y = filtfilt(b, a, data)
        y = scipy.signal.sosfiltfilt(sos, data)
        return y
    
    def butter_highpass_filter(self,data, cutOff, fs, order=4, zi=None):
        sos = self.butter_highpass_coeff(cutOff, fs, order=order)
        #y = filtfilt(b, a, data)
        y = scipy.signal.sosfiltfilt(sos, data)
        return y










class MainWindow(QtWidgets.QMainWindow):

    def closeEvent(self, event):
        self.db_client.close()
        self.db_client_thread.terminate()

    def save_config(self):
        try:
            json.dump(self.config, open('config.json', 'w+'))
        except PermissionError as err:
            pass

    # The method name "on_button_measurement_clicked" led to a double signal being emitted and consequently double
    # entries in the database. Therefore, a different name was chosen with separate connection.
    def button_save_measurement_clicked(self):
        # Create temporary dictionary with single measurement
        try:
            unixStart = datetime.datetime.timestamp(datetime.datetime.strptime(self.ui.startLineEdit.text(),"%m/%d/%Y, %H:%M:%S" ))
            unixStop = datetime.datetime.timestamp(datetime.datetime.strptime(self.ui.stopLineEdit.text(),"%m/%d/%Y, %H:%M:%S" ))
        except:
            QMessageBox.about(self, "Wrong Timestring", "Could not Parse Start or Stop Time, please check")
            return 0

        if not any(char.isdigit() for char in self.ui.lineEdit.text()):
            QMessageBox.about(self, "Id Format", "Measurement Id must contain at least one number")
            return 0
        
        if self.db_client.checkMeasurement(self.ui.lineEdit.text()):

            temp_dict = {'measurement_id': self.ui.lineEdit.text(), 'comments': self.ui.textEdit.toPlainText(),
                     'sensor_id': int(self.ui.nodeSelector.cleanText()), 'meas_start': unixStart,
                     'meas_stop': unixStop, 'processed': False}
            # call insertMeasurements method of the db_client class
            self.db_client.insertMeasurements(temp_dict)
            QMessageBox.about(self, "Measurement Created", "Created Measurement")
            
        else:
            
            QMessageBox.about(self, "Error", "Duplicate ID, please choose different ID")


    def on_button_start_meas_clicked(self):
        now = datetime.datetime.now()
        self.ui.startLineEdit.setText(now.strftime("%m/%d/%Y, %H:%M:%S"))

    def on_button_stop_meas_clicked(self):
        
        now = datetime.datetime.now()
        self.ui.stopLineEdit.setText(now.strftime("%m/%d/%Y, %H:%M:%S"))


            
            
            
    def timerUpdate(self):
        
        sensorOffset = int(self.ui.nodeSelector.cleanText())*4
        
        sensor = int(self.ui.sensorSelector.cleanText()) - 1
            
        data = self.db_client.getPacket(sensorOffset + sensor,5)
        series = []
        
        for packet in data:
            series.append(self.parser.parse(packet[5]))
    
        try:     
            samples = np.concatenate(series)
        except:
            return 0
        self.iqTrace.setData(samples[:,0],samples[:,1])
        dispsize = np.shape(samples)[0]
        
        
        self.rad_i = self.filter_fun.butter_highpass_filter(samples[:,0] ,0.2, FS)
        self.rad_q = self.filter_fun.butter_highpass_filter(samples[:,1] ,0.2, FS)
    
        self.rad = np.sqrt(np.square(self.rad_i)+np.square(self.rad_q))
        self.hs = self.filter_fun.butter_bandpass_filter(self.rad, 15, 80, FS)
        
        self.hsTrace.setData(np.linspace(0, dispsize/FS, dispsize), self.hs)
        
 
        
    def slowtimerUpdate(self):
        
        sensorOffset = int(self.ui.nodeSelector.cleanText())*4
        
        
        
        if (self.db_client.getRadStat(sensorOffset + 0) > 0):
            self.sensor1_led.setPixmap(self.green_led)
        else:
            self.sensor1_led.setPixmap(self.red_led)
        
        if (self.db_client.getRadStat(sensorOffset + 1) > 0):
            self.sensor2_led.setPixmap(self.green_led)
        else:
            self.sensor2_led.setPixmap(self.red_led)
            
        if (self.db_client.getRadStat(sensorOffset + 2) > 0):
            self.sensor3_led.setPixmap(self.green_led)
        else:
            self.sensor3_led.setPixmap(self.red_led)
            
        if (self.db_client.getRadStat(sensorOffset + 3) > 0):
            self.sensor4_led.setPixmap(self.green_led)
        else:
            self.sensor4_led.setPixmap(self.red_led)
        
        
        
    ######################################################
    # INIT ###############################################
    ######################################################
    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)

        # Load the UI Page
        self.ui = uic.loadUi('./ui/EmpkinsGUI.ui', self)

        ###################################
        # Set icons as pixmap in GUI header
        sensor_icon = QtGui.QPixmap('./ui/icons/ICON_sensorik.png')
        sensor_icon = sensor_icon.scaledToWidth(50, 1)  # 1 for high quality, 0 for low quality pixmap
        self.sensor_icon.setPixmap(sensor_icon)

        empkins_icon = QtGui.QPixmap('./ui/icons/FAU_SFB EmpkinS_Logo_CMYK.png')
        empkins_icon = empkins_icon.scaledToWidth(100, 1)
        self.empkins_icon.setPixmap(empkins_icon)

        ###########################################################
        # Check for existing config file - create one if none found
        config_file = Path('config.json')
        if config_file.exists():
            self.config = json.load(open('config.json', 'r'))
            dbFilename = self.config.get('DBFilename')
        else:
            self.config = dict()  # Empty dict, DB file selected via QFiledialog
            dbFilename, filter = QtWidgets.QFileDialog.getOpenFileName(parent=self, caption='Select SQlite file',
                                                                       directory='.', filter='SQlite Files (*.*)')
            self.config['DBFilename'] = dbFilename
            json.dump(self.config, open('config.json', 'w+'))

        ############################
        # Connect to SQlite database
        self.db_client_thread = QThread()   # Empty thread
        self.db_client = SQliteClient(dbFilename)   # Initiate instance of class SQliteClient

        self.db_client.moveToThread(self.db_client_thread)  # Execute client in thread
        self.db_client_thread.started.connect(self.db_client.start)     # start client if thread is started
        self.db_client_thread.start()   # start thread --> starts db_client

        ########################
        # Connection for methods
        self.ui.button_save_measurement.clicked.connect(self.button_save_measurement_clicked)



        # TO-DO ##################################################
        # Statusabfrage an den Master --> implementieren
        # while:
        #   -Status-Abfrage an den Server erfolgreich
        #   Status anzeigen
       

        # Statusabfrage an die Sensoren --> implementieren
        # While
        #   all radar sensors send data
        #   display all sensors as functional
        
        self.red_led = QtGui.QPixmap('./ui/icons/red_led.png')
        self.red_led = self.red_led.scaledToWidth(30, 1)
        
        
        self.green_led = QtGui.QPixmap('./ui/icons/green_led.png')
        self.green_led = self.green_led.scaledToWidth(30, 1)      
        
        
        
        self.sensor1_led.setPixmap(self.red_led)
        self.sensor2_led.setPixmap(self.red_led)
        self.sensor3_led.setPixmap(self.red_led)
        self.sensor4_led.setPixmap(self.red_led)
############################################################
   
        
        self.parser = emRadParser()

        self.iqWidget.setBackground('k')
        self.iqWidget.showGrid(True,True)
        self.iqTrace = self.iqWidget.plot()
        
        
        self.heartbeatWidget.setBackground('k')
        self.heartbeatWidget.showGrid(True,True)
        self.hsTrace = self.heartbeatWidget.plot(name="Heartsounds")



        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.timerUpdate)
        self.timer.setInterval(200)
        self.timer.start()
        
        self.slowtimer = QtCore.QTimer()
        self.slowtimer.timeout.connect(self.slowtimerUpdate)
        self.slowtimer.setInterval(2000)
        self.slowtimer.start()
        
        
        self.filter_fun = TemporalFilters()

def main():
    app = QtWidgets.QApplication(sys.argv)

    apply_stylesheet(app, theme='dark_blue.xml')

    main = MainWindow()
    main.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
