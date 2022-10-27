

import sys
from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QCloseEvent
from PySide6.QtCore import Qt
from PySide6.QtCore import QThread, QFile
from PySide6.QtUiTools import QUiLoader
from pathlib import Path
import json

from lib.udp import UDPServer
from lib.SQlite import SQliteClient
from lib.mparse import UDPParser


QtWidgets.QApplication.setAttribute(
    QtCore.Qt.AA_EnableHighDpiScaling, True)  # enable highdpi scaling
QtWidgets.QApplication.setAttribute(
    QtCore.Qt.AA_UseHighDpiPixmaps, True)  # use highdpi icons


class emRadServer(QtWidgets.QWidget):

    def closeEvent(self):
        
        self.message_parser_thread.exit()
        try:
            self.db_client.close()
            self.db_client_thread.terminate()

        except:
            pass
        try:
            self.udp_server.close()
            self.udp_thread.terminate()
        except:
            pass

    def __init__(self):
        super(emRadServer, self).__init__()
        self.status_message = ['● Idle', '● Idle', '']

        config_file = Path('config.json')

        if config_file.exists():
            self.config = json.load(open('config.json', 'r'))
        else:
            self.config = dict()
            json.dump(self.config, open('config.json', 'w+'))
            
        # Create Message Parser
        self.message_parser_thread = QThread()
        self.message_parser = UDPParser()
        self.message_parser.moveToThread(self.message_parser_thread)
        self.message_parser_thread.start()

        """Load UI"""
        ui_file_name = "./ui/mainwindow_minimal.ui"
        ui_file = QFile(ui_file_name)
        loader = QUiLoader()
        self.ui = loader.load(ui_file)
        # self.ui = uic.loadUi('mainwindow.ui', self)
        ui_file.close()
        self.init_ui()
        self.ui.closeEvent = self.closeEvent

        
        self.ui.button_DbClient.clicked.connect(
            self.on_db_client_connect_button_clicked
        )

        self.ui.button_Udp.clicked.connect(
            self.on_udp_server_start_stop_button_clicked
        )
          
        self.ui.button_DbClient_select.clicked.connect(
            self.on_button_DbClient_select_clicked
        )

        self.ui.tabWidget.currentChanged.connect(
            self.on_tab_changed
        )

        self.ui.show()
        
        db_file = Path(self.ui.lineEdit_DbFile.text())
        
        if db_file.exists():
           # self.on_db_client_connect_button_clicked()
            self.on_udp_server_start_stop_button_clicked()
                
        
    def save_config(self):
        try:
            json.dump(self.config, open('config.json', 'w+'))
        except PermissionError as err:
            pass

    def init_ui(self):
        # Interface

        self.ui.tabWidget.setCurrentIndex(self.config.get('Tab_Index', 0))
        self.on_tab_changed(self.config.get('Tab_Index', 0))

        # TCP Client
        self.ui.textBrowser_DbClientMessage.setEnabled(False)

        # UDP
        udp_listen_port = self.config.get('UDP_Listen_Port', '300')

        self.ui.lineEdit_UdpListenPort.setText(udp_listen_port)
        
        dbFilename = self.config.get('DBFilename')

        self.ui.lineEdit_DbFile.setText(dbFilename)
        self.save_config()


    def on_button_DbClient_select_clicked(self):
        filename, filter = QtWidgets.QFileDialog.getOpenFileName(parent=self, caption='Open file', dir='.', filter='SQlite Files (*.*)')
        self.ui.lineEdit_DbFile.setText(filename)
        self.config['DBFilename'] = filename
        self.save_config()
        
    # Db Client
    def on_db_client_connect_button_clicked(self):
        if self.ui.button_DbClient.text() == 'Connect':
            
            self.ui.button_DbClient.setEnabled(False)
            self.ui.lineEdit_DbFile.setEnabled(False)

            # Start SQlite instance in separate thread from selected file in lineEdit_DbFile
            self.db_client_thread = QThread()
            self.db_client = SQliteClient(
                self.ui.lineEdit_DbFile.text())

            self.db_client_thread.started.connect(self.db_client.start)
            self.db_client.status.connect(self.on_db_client_status_update)
            self.db_client.message.connect(self.on_db_client_message_update)
            self.db_client.stats.connect(self.on_db_client_stats_update)


            # self.db_client.start()
            self.db_client.moveToThread(self.db_client_thread)

            self.db_client_thread.start()
            self.message_parser.message.connect(self.db_client.insertPackets)


        elif self.ui.button_DbClient.text() == 'Disconnect':
            self.ui.button_DbClient.setEnabled(False)
            self.db_client.close()
            self.message_parser.message.disconnect()

    def on_db_client_status_update(self, status):
        if status == SQliteClient.STOP:
            self.db_client.status.disconnect()
            self.ui.textBrowser_DbClientMessage.append('Disconnected')
            self.ui.button_DbClient.setText('Connect')
            self.db_client_thread.quit()

            self.ui.lineEdit_DbFile.setEnabled(True)

            self.status_message[0] = '● Idle'
            
            if self.ui.tabWidget.currentIndex() == 0:
                self.on_tab_changed(0)

        elif status == SQliteClient.CONNECTED:
            self.ui.textBrowser_DbClientMessage.append('Connected')
            self.ui.button_DbClient.setText('Disconnect')

            self.ui.textBrowser_DbClientMessage.setEnabled(True)
            self.status_message[0] = '● Connected to Database'
            if self.ui.tabWidget.currentIndex() == 0:
                self.on_tab_changed(0)

        self.ui.button_DbClient.setEnabled(True)


        
    def on_db_client_message_update(self, message):
        self.ui.textBrowser_DbClientMessage.append(
            message)

    def on_db_client_stats_update(self,stats):
        self.ui.db_tp_label.setText("%d Packets per Second"%stats)

    # UDP
    def on_udp_server_start_stop_button_clicked(self):
        if self.ui.button_Udp.text() == 'Start':
            self.ui.button_Udp.setEnabled(False)
            self.ui.lineEdit_UdpListenPort.setEnabled(False)
            self.udp_thread = QThread()
            self.udp_server = UDPServer('0.0.0.0',                int(self.ui.lineEdit_UdpListenPort.text()))
            self.config['UDP_Listen_Port'] = self.ui.lineEdit_UdpListenPort.text()

            self.udp_thread.started.connect(self.udp_server.start)
            self.udp_server.status.connect(self.on_udp_server_status_update)
            self.udp_server.message.connect(self.message_parser.parse)
            self.udp_server.stats.connect(self.on_udp_server_stats_update)

            self.udp_server.moveToThread(self.udp_thread)

            self.udp_thread.start()

            self.config['UDP_Listen_Port'] = self.ui.lineEdit_UdpListenPort.text()
            self.save_config()

        elif self.ui.button_Udp.text() == 'Stop':
            self.ui.button_Udp.setEnabled(False)
            self.udp_server.close()

    def on_udp_server_status_update(self, status, addr):
        if status == UDPServer.STOP:
            self.udp_server.status.disconnect()
            self.udp_server.message.disconnect()

            self.ui.button_Udp.setText('Start')
            # self.tcp_server_thread.terminate()
            self.udp_thread.quit()

            self.ui.lineEdit_UdpListenPort.setEnabled(True)
            self.status_message[1] = '● Idle'
            if self.ui.tabWidget.currentIndex() == 1:
                self.on_tab_changed(1)

        elif status == UDPServer.LISTEN:
            self.ui.button_Udp.setText('Stop')
            self.status_message[1] = '● Listen on ' +\
                self.ui.lineEdit_UdpListenPort.text()
            if self.ui.tabWidget.currentIndex() == 1:
                self.on_tab_changed(1)

        self.ui.button_Udp.setEnabled(True)

    def on_udp_server_message_ready(self, source, msg):
        self.ui.textBrowser_UdpMessage.append(
            '<p style="text-align: center;"><span style="color: #2196F3;"><strong>----- ' +
            source +
            ' -----</strong></span></p>')
        self.ui.textBrowser_UdpMessage.append(
            '<p style="text-align: center;"><span style="color: #2196F3;">' +
            msg +
            '</span></p>')

    def on_udp_server_stats_update(self,stats):
        self.ui.nw_tp_label.setText("%d Packets per Second"%stats)

    def on_tab_changed(self, index):
        self.ui.status_bar.clearMessage()
        self.ui.status_bar.setStyleSheet('color: green')
        self.ui.status_bar.showMessage(self.status_message[index])

        self.config['Tab_Index'] = self.ui.tabWidget.currentIndex()
        
        self.ui.db_status_label.setText(self.status_message[0])
        self.ui.nw_status_label.setText(self.status_message[1])

        self.save_config()


if __name__ == "__main__":
    
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    if not QtWidgets.QApplication.instance():
        app = QtWidgets.QApplication(sys.argv)
    else:
        app = QtWidgets.QApplication.instance()
    window = emRadServer()
    app.aboutToQuit.connect(window.closeEvent)

    sys.exit(app.exec())
