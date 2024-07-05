# -*- coding: utf-8 -*-
"""

@author: Marcus Heide, Paul Tschammer

Modified by Nils Albrecht for IHF Radar over Serial

"""

import numpy as np
import csv
import serial
import pyqtgraph as pg
from PyQt5.QtCore import QThread, Qt, QObject, QThread, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import QPushButton, QApplication, QMainWindow, QHBoxLayout, QVBoxLayout, QWidget, QLabel, QToolBar, QAction, QSplitter
import ctypes
from scipy.signal import sosfilt, butter, lfilter, lfilter_zi, sosfilt_zi#filtfilt as filtfilt, detrend as detrend
import socket

import sys
from time import sleep#,strftime
from struct import unpack
import timeit
import configparser
from datetime import datetime
from cobs import cobs

config = configparser.ConfigParser()
config.read('config.ini')

OVERSAMPLING = 1  
PACKETSIZE = 32


BLOCKSZ = 1 
BUFFERSZ = 32

SUBBUFFERNUM = 8


#EDIT HERE


Node=0


####


FS = 8e6 / 1024 / 8


FS = int(round(FS))

xoff = 0
yoff = 0

Radar_Freq_Hz = 62*1e9 # 122 GHz
C_Light_Air_mps = 299708516 # reduzierte Lichtgeschwindigkeit in bodennaher Luft
Radian2Meter = C_Light_Air_mps/(4*np.pi*Radar_Freq_Hz)
Radian2Degree = 180/np.pi

SLEEP = BUFFERSZ/FS/SUBBUFFERNUM*0.8
print('Pausing get_latest_samples %f ms' % (SLEEP*1000)) # momentan auf einmal pro Sekunde limitiert

WFPS = 30 #30 # Updaterate/Framerate der Plots
SGFPS = 1#5
DATARECORDTIME = 10
SPECTIME = 1 # Spectrogamlänge
PHASETIME = 5
FILENAME = 'Output Data_%iMS_%ios_%is.csv' % (FS//1e6,OVERSAMPLING,DATARECORDTIME)

print('Data refresh intervall is %5.2f Buffer/seconds' % round(FS/BUFFERSZ)) # Ausgabe der Framerate
print('Widget refresh rate is %i fps' % WFPS) # momentan auf einmal pro Sekunde limitiert

# np.seterr(divide = 'ignore', invalid='ignore') # Logarithmus von Null Fehler ignorieren







class TemporalFilters():
        #Funktionen Filter
    def butter_bandpass_coeff(self,lowcut, highcut, fs, order=5):
        nyq = 0.5 * fs
        low = lowcut / nyq
        high = highcut / nyq
        sos = butter(order, [low, high], btype='band', analog = False, output='sos')
        return sos
    
    
    def butter_bandpass_filter(self,data, lowcut, highcut, fs, order=5, zi=None):
        b, a = self.butter_bandpass_coeff(lowcut, highcut, fs, order=order)
        #y = filtfilt(b, a, data)
        y = lfilter(b, a, data, zi)
        return y
    
    def butter_lowpass_coeff(self,cutOff, fs, order=5):
       
        sos = butter(order, cutOff, btype='lowpass', analog = False, output='sos', fs=fs)
        return sos
        
    def butter_highpass_coeff(self,cutOff, fs, order=5):
       
        sos = butter(order, cutOff, btype='highpass', analog = False, output='sos', fs=fs)
        return sos
    
    def butter_lowpass_filter(self,data, cutOff, fs, order=4, zi=None):
        b, a = self.butter_lowpass_coeff(cutOff, fs, order=order)
        #y = filtfilt(b, a, data)
        y = lfilter(b, a, data, zi)
        return y




class UDPServer(QObject):
    status = pyqtSignal(int, object)
    message = pyqtSignal(object, object)
    stats = pyqtSignal(int)

    ERROR = -1
    LISTEN = 1
    CONNECTED = 2
    STOP = 3

    SIG_NORMAL = 0
    SIG_STOP = 1
    SIG_DISCONNECT = 2

    def __init__(self, ip, port):
        QObject.__init__(self)

        self.ip = ip
        self.port = port
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.udp_socket.settimeout(0.1)

        self.pyqtSignal = self.SIG_NORMAL



    @pyqtSlot()
    def start(self):
        try:
            self.udp_socket.bind((self.ip, self.port))
            
        except OSError as err:
            self.status.emit(self.STOP, '')
        else:
            self.status.emit(self.LISTEN, '')
            while True:
                if self.pyqtSignal == self.SIG_NORMAL:
                    # self.status.emit(self.LISTEN, '')
                    try:
                        data, addr = self.udp_socket.recvfrom(4096)
                    except socket.timeout as t_out:
                        pass
                    else:
                        if data:
                            print(len(data))
                            if (len(data) == 1308):
                                temp = np.reshape(unpack('<320i', data[28:]), (32, 10))
                                sendbufferI = np.copy(temp[:, Node * 2])
                                sendbufferQ = np.copy(temp[:, Node * 2 + 1])

                    else:
                            self.status.emit(self.LISTEN, '')
                            break
                elif self.pyqtSignal == self.SIG_STOP:
                    self.pyqtSignal = self.SIG_NORMAL
                    self.udp_socket.close()
                    # self.status.emit(self.LISTEN, '')
                    break
           
        finally:
            self.status.emit(self.STOP, '')


    def close(self):
        self.pyqtSignal = self.SIG_STOP
        





    
class WaveformCalcThread(QThread):
    sampleshot_pyqtSignal = pyqtSignal(np.ndarray,np.ndarray)
    phase_pyqtSignal = pyqtSignal(np.ndarray)
    heartsound_pyqtSignal = pyqtSignal(np.ndarray)
    heartsound_short_pyqtSignal = pyqtSignal(np.ndarray)
    sandbox_pyqtSignal = pyqtSignal(np.ndarray)
    def __init__(self, parent = None):
        QThread.__init__(self, parent)
        self.exiting = False
        
        self.samp2disp = int(PHASETIME*FS)
        # self.wrapped_phase = np.empty(self.samp2disp)
        # self.wrapped_raw_phase_disp = np.empty(self.samp2disp)#self.samp2disp)
        self.unwrapped_raw_phase = np.empty(BUFFERSZ)#, dtype='float32')
        self.unwrapped_raw_phase_disp = np.empty(self.samp2disp)
        self.heartsound_disp = np.empty(self.samp2disp)
        self.audio_disp = np.empty(self.samp2disp)

        self.sandbox_i_disp = np.empty(self.samp2disp)
        self.sandbox_q_disp = np.empty(self.samp2disp)
        self.sandbox_iq_envelope_disp = np.empty(self.samp2disp)
        self.wrapped_sandbox_phase_disp = np.empty(self.samp2disp)
        self.unwrapped_sandbox_phase_disp = np.empty(self.samp2disp)
        
        self.i_data_buffer_disp = np.empty(self.samp2disp)
        self.q_data_buffer_disp = np.empty(self.samp2disp)
        
        self.update_count = 0
        self.save_count = 0
        self.isRecording = False
        self.nextSample = 0
        self.initialized = False
        
        filter_fun = TemporalFilters()
        self.sos_heartsound = filter_fun.butter_bandpass_coeff(18, 80, FS, order=4)#18 80
        #self.b_heartsound, self.a_heartsound = filter_fun.iir_bandpass_coeff(0.6, 2.0, FS, order=4)#18 80
        self.zi_heartsound = sosfilt_zi(self.sos_heartsound)
        
        self.sos_audio = filter_fun.butter_bandpass_coeff(0.6, 4, FS, order=4)#18 80
        #self.b_heartsound, self.a_heartsound = filter_fun.iir_bandpass_coeff(0.6, 2.0, FS, order=4)#18 80
        self.zi_audio = sosfilt_zi(self.sos_audio)
        
        
   
    #@pyqtSlot()
    def updateData(self,i_data,q_data):
        
        self.i_data_buffer = i_data - yoff
        self.q_data_buffer = q_data - xoff
        #print("got")
        #print(self.i_data_buffer)

        self.start()
        
    def run(self):
        
        self.update_count += 1
        
        self.i_data_buffer_disp = np.concatenate((self.i_data_buffer_disp[PACKETSIZE:],self.i_data_buffer))
        self.q_data_buffer_disp = np.concatenate((self.q_data_buffer_disp[PACKETSIZE:],self.q_data_buffer))
        
        self.wrapped_raw_phase = np.arctan2(self.q_data_buffer,self.i_data_buffer)
        
        if not self.initialized:
            self.unwrapped_raw_phase = self.wrapped_raw_phase
            self.heartsound, self.zi_heartsound = sosfilt(self.sos_heartsound, self.unwrapped_raw_phase, zi=self.zi_heartsound*self.unwrapped_raw_phase[0])
            self.audio, self.zi_audio = sosfilt(self.sos_audio, self.unwrapped_raw_phase, zi=self.zi_audio*self.unwrapped_raw_phase[0])

            self.unwrapped_raw_phase = np.unwrap(self.wrapped_raw_phase)
            self.initialized = True
        else:
            self.unwrapped_raw_phase = np.unwrap(np.hstack((self.prior_raw_phase,self.wrapped_raw_phase)))[1:]
            self.heartsound, self.zi_heartsound = sosfilt(self.sos_heartsound, self.unwrapped_raw_phase, zi=self.zi_heartsound)
            self.audio, self.zi_audio = sosfilt(self.sos_audio, self.unwrapped_raw_phase, zi=self.zi_audio)

        
        self.prior_raw_phase = self.unwrapped_raw_phase[-1] #letztes Sample behalten für das Unwraping mit den kommenden Samples
        self.unwrapped_raw_phase_disp = np.concatenate((self.unwrapped_raw_phase_disp[PACKETSIZE::],self.unwrapped_raw_phase))     
        self.audio_disp = np.concatenate((self.audio_disp[PACKETSIZE::],self.audio))

        self.heartsound_disp = np.concatenate((self.heartsound_disp[PACKETSIZE::],self.heartsound))
        
     
        
        if WFPS == 0 or self.update_count >= FS/BUFFERSZ/WFPS: # alle x WFPS aufrufen
            self.sampleshot_pyqtSignal.emit(self.i_data_buffer_disp,self.q_data_buffer_disp)
            #self.phase_pyqtSignal.emit(self.unwrapped_raw_phase_disp*Radian2Meter)
            self.phase_pyqtSignal.emit(self.audio_disp)
            self.heartsound_pyqtSignal.emit((self.heartsound_disp*Radian2Meter))
            ##print(max(self.heartsound_disp*Radian2Meter))
            #self.heartsound_short_pyqtSignal.emit(self.heartsound*Radian2Meter)
            self.heartsound_short_pyqtSignal.emit(self.audio)
            self.update_count = 0
            
            u = np.array(self.i_data_buffer_disp)
            v = np.array(self.q_data_buffer_disp)
  

        
#method_1 = 'algebraic'
# linear system defining the center in reduced coordinates (uc, vc):
#    Suu * uc +  Suv * vc = (Suuu + Suvv)/2
#    Suv * uc +  Svv * vc = (Suuv + Svvv)/2
# coordinates of the barycenter
            x_m = np.mean(u)
            y_m = np.mean(v)
        
# calculation of the reduced coordinates
            u = u - x_m
            v = v - y_m

            Suv  = sum(u*v)
            Suu  = sum(u**2)
            Svv  = sum(v**2)
            Suuv = sum(u**2 * v)
            Suvv = sum(u * v**2)
            Suuu = sum(u**3)
            Svvv = sum(v**3)
        
# Solving the linear system
            A = np.array([ [ Suu, Suv ], [Suv, Svv]])
            B = np.array([ Suuu + Suvv, Svvv + Suuv ])/2.0
            xc_1, yc_1 = np.linalg.solve(A, B)


# Calculation of all distances from the center (xc_1, yc_1)
            Ri_1      = np.sqrt((u-xc_1)**2 + (v-yc_1)**2)
            R_1       = np.mean(Ri_1)
            residu_1  = sum((Ri_1-R_1)**2)
            residu2_1 = sum((Ri_1**2-R_1**2)**2)
        
            xc_1 = x_m + xc_1
            yc_1 = y_m + yc_1
            
            #print("CenterX:{0},CenterY:{1},Radius:{2}".format(xc_1,yc_1,R_1))
            print("Radius:{0}".format(R_1))


            
            
            

    def __del__(self):
        self.exiting = True
        self.wait()
        
        
        
        
class memThread(QThread):
    sampleshot_pyqtSignal = pyqtSignal(np.ndarray,np.ndarray)
    
    def __init__(self, parent = None):
        
        QThread.__init__(self, parent)
        self.file = None
   
    def startRec(self):
        now = datetime.now()
        DATARECORDTIME = now.strftime("%H_%M_%S")
        FILENAME = 'IMS_SDC_%i_kSps_%s.csv' % (FS,DATARECORDTIME)
        self.file = open(FILENAME, 'w+', newline ='')
        self.write = csv.writer(self.file)
    
    
    def stopRec(self):
        self.file.close()

        
    def updateData(self,i_data,q_data):
        self.data = np.column_stack((i_data,q_data))
        
        if self.file != None:
            if self.file.closed == False: 
                self.write.writerows(self.data)
  
               

    def __del__(self):
        self.file.close()
        
        

        
class WaveformWidget(pg.PlotWidget):
    def __init__(self, title='', background='w'):
        super().__init__(title=title,background=background)
        # self.setStyleSheet('margin: 10px solid {background};'.format(background=background))
        self.showGrid(True, True, 0.7)
        self.samp2disp = int(PHASETIME*FS/BLOCKSZ)#*BLOCKSZ
        
        self.p1 = self.plotItem
        self.p1.setLabels(left='Q')
        self.p1.getAxis('left').setLabel(units='V')
        self.setLabel('bottom', 'I', units='V')
        self.p1.setAspectLocked()
        self.iq_plot = self.p1.plot(np.zeros(self.samp2disp),np.zeros(self.samp2disp),pen=pg.mkPen(color='b'))
    
    def updateData(self,i_data,q_data):#,c_data):
        self.iq_plot.setData(q_data  ,i_data )
        

    def mousePressEvent(self, event):
        global xoff, yoff
        xoff = self.p1.vb.mapSceneToView(event.pos()).x() + xoff
        yoff = self.p1.vb.mapSceneToView(event.pos()).y() + yoff

        

class PhaseWidget(pg.PlotWidget):
    def __init__(self, title='',x_label='',x_unit='', y_label='',y_unit='', y_limits=None, plot_dim=1, color='b',background='white'):
        super().__init__(title=title,background=background)
        # self.setStyleSheet('border: 5px solid {background};'.format(background=background))
        self.showGrid(True, True, 0.7)
        self.phase2dispNum = int(PHASETIME*FS/BLOCKSZ)
        self.time = np.linspace(0,PHASETIME,self.phase2dispNum)
        self.color = color

        self.p1 = self.plotItem
        self.p1.setLabels(left=y_label)
        self.p1.getAxis('left').setLabel(units=y_unit, color=color)
        self.setLabel('bottom', x_label, units=x_unit)
        if not y_limits is None:
            self.setLimits(yMin=y_limits[0],yMax=y_limits[1]) 
        self.dummy_data = np.zeros(self.phase2dispNum)

        self.phase_plot1 = self.p1.plot(self.time, self.dummy_data, pen=pg.mkPen(color=color))            
        if plot_dim > 1:
            self.phase_plot2 = self.p1.plot(self.time, self.dummy_data, pen=pg.mkPen(color='r'))
            if plot_dim > 2:
                # self.phase_plot3 = self.p1.plot(self.time, self.dummy_data, pen=pg.mkPen(color='k'))
                
                self.p2 = pg.ViewBox()
                self.p1.showAxis('right')
                self.p1.scene().addItem(self.p2)
                self.p1.getAxis('right').linkToView(self.p2)
                self.p2.setXLink(self.p1)
                self.p1.getAxis('right').setLabel('Phase', units='m', color='#ff0000')
                self.phase_plot3 = pg.PlotCurveItem(self.time, self.dummy_data, pen=pg.mkPen(color='k'))
                self.p2.addItem(self.phase_plot3)
                self.p2.setGeometry(self.p1.vb.sceneBoundingRect())
                self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)
                # self.updateViews()
                self.p1.vb.sigResized.connect(self.updateViews)

    def updateData(self, phase_data1,phase_data2=None,phase_data3=None):
        self.phase_plot1.setData(self.time, phase_data1)
        if phase_data2 is not None:
            self.phase_plot2.setData(self.time, phase_data2) 
        if phase_data3 is not None:
            self.phase_plot3.setData(self.time, phase_data3)
            # self.p2.setGeometry(self.p1.vb.sceneBoundingRect())

    def updateViews(self):
    #     ## view has resized; update auxiliary views to match
        self.p2.setGeometry(self.p1.vb.sceneBoundingRect())
    #     self.p3.setGeometry(self.p1.vb.sceneBoundingRect())
        
    #     ## need to re-update linked axes since this was called
    #     ## incorrectly while views had different shapes.
    #     ## (probably this should be handled in ViewBox.resizeEvent)
        self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)

class GUARDIAN(QMainWindow):
    def __init__(self, parent=None, background_color='#FFFFFF'):
        super().__init__(parent)
        self.setWindowTitle('GROOT MR v0.1')
        self.setStyleSheet('background-color: {background_color};'.format(background_color=background_color)) 
        self.height = 920
        self.resize(1600,self.height)
        # self.background='#FFFFFF'
        # opening window in maximized size
        self.showMaximized()
  
        
        self.main_box = QSplitter(Qt.Horizontal)#QVBoxLayout()
        self.iq_widget = WaveformWidget(title='IQ-Darstellung',background=background_color)
        self.main_box.addWidget(self.iq_widget)
        
        self.right_box = QSplitter(Qt.Vertical)
        self.main_box.addWidget(self.right_box)
        
        self.phase_widget = PhaseWidget(title='Relative Abstandsänderung',x_label='Zeit',x_unit='s',y_label='Abstand',y_unit='m',background=background_color)
        self.right_box.addWidget(self.phase_widget)
        
        self.heartsound_widget = PhaseWidget(title='Herztöne',x_label='Zeit',x_unit='s',y_label='Amplitude',y_unit='m',background=background_color,y_limits=[-8e6,8e6],color='r')
        self.right_box.addWidget(self.heartsound_widget)
        
        # self.sandbox_widget = PhaseWidget(title='Hüllkurve',x_label='Zeit',x_unit='s',y_label='Amplitude',y_unit='V',y_limits=[0,3e-3],plot_dim=1,color='b',background=background_color)
        # self.right_box.addWidget(self.sandbox_widget)
        
        # self.right_box.setSizes([self.height*0.4,self.height*0.4,self.height*0.2])
        
        # self.main_layout = QHBoxLayout()
        # self.main_layout.addWidget(self.main_box)
        # self.main_layout.addWidget(self.right_box) 

        # self.main_widget = QWidget()
        # self.main_widget.addWidget(self.main_box)
        self.setCentralWidget(self.main_box)
        
        self.right_box.setSizes([self.height*0.4,self.height*0.4,self.height*0.2])

        self.wfthread = WaveformCalcThread()
        #self.sndthread = SoundThread()
        self.wfthread.sampleshot_pyqtSignal.connect(self.iq_widget.updateData)
        self.wfthread.phase_pyqtSignal.connect(self.phase_widget.updateData)
        self.wfthread.heartsound_pyqtSignal.connect(self.heartsound_widget.updateData)
        #self.wfthread.heartsound_short_pyqtSignal.connect(self.sndthread.updateData)
        # self.wfthread.sandbox_pyqtSignal.connect(self.sandbox_widget.updateData)
        
        
        self.udp_thread2 = QThread(self)
        #self.udp_server = UDPServer("192.168.178.1", 300)
        
        self.udp_server = UDPServer("127.0.0.1", 2000)
        self.udp_thread2.started.connect(self.udp_server.start)
        self.udp_server.moveToThread(self.udp_thread2)
        self.udp_thread2.start()
        
        #self.pico = Serial()
        #self.thread = QThread(self)
        #self.pico.moveToThread(self.thread)
        #self.thread.started.connect(self.pico.run)
        self.memory = memThread()
        
        
        self.udp_server.message.connect(self.wfthread.updateData)
        #self.pico.mV_output.connect(self.wfthread.updateData)
        #self.pico.mV_output.connect(self.memory.updateData)
        #self.thread.start()
        
        self.button1 = QPushButton(self.right_box)
        self.button1.setText("Start Rec")
        
        self.button2 = QPushButton(self.right_box)
        self.button2.setText("Stop Rec")
       
        self.button1.clicked.connect(self.memory.startRec)
        
        self.button2.clicked.connect(self.memory.stopRec)
        
            
    def closeEvent(self, event):
        self.udp_server.close()
        self.udp_thread2.quit()
        #self.pico.stop()
        #self.thread.quit()
        QApplication.quit() # essentiell, damit Spyder die Konsole wieder freigibt 

if __name__ == '__main__':
    def run_app():
        app = QApplication(sys.argv)
        mainwindow = GUARDIAN()
        mainwindow.show()
        app.exec_()
        
        print('Closing of App successfull')
    run_app()
