"""
    Copyright (C) 2017 - 2021  Zhengyu Peng, https://zpeng.me

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

    Modified by Nils Albrecht

"""

from PySide6.QtCore import QObject, Signal, Slot,QTimer,QDateTime
import socket
import datetime


class UDPServer(QObject):
    status = Signal(int, object)
    message = Signal(object, object)
    stats = Signal(int)

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
        self.udp_socket.settimeout(0.1)

        self.signal = self.SIG_NORMAL
        self.time = datetime.datetime.now().timestamp()
        self.packetcounter = 1



    @Slot()
    def start(self):
        try:
            self.udp_socket.bind((self.ip, self.port))
            
        except OSError as err:
            self.status.emit(self.STOP, '')
        else:
            self.status.emit(self.LISTEN, '')
            while True:
                if self.signal == self.SIG_NORMAL:
                    # self.status.emit(self.LISTEN, '')
                    try:
                        data, addr = self.udp_socket.recvfrom(4096)
                    except socket.timeout as t_out:
                        pass
                    else:
                        if data:
                            
                            self.message.emit(datetime.datetime.now().timestamp(), data)
                            self.packetcounter += 1
                        else:
                            self.status.emit(self.LISTEN, '')
                            break
                elif self.signal == self.SIG_STOP:
                    self.signal = self.SIG_NORMAL
                    self.udp_socket.close()
                    # self.status.emit(self.LISTEN, '')
                    break
                if self.time + 0.1 < (datetime.datetime.now().timestamp()):
                    self.time = datetime.datetime.now().timestamp()
                    self.stats.emit(self.packetcounter*10)
                    self.packetcounter=0;
        finally:
            self.status.emit(self.STOP, '')

    def send(self, msg, ip, port):
        self.udp_socket.sendto(msg.encode(), (ip, port))


    def close(self):
        self.signal = self.SIG_STOP
        

