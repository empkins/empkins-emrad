
from PySide6.QtCore import QObject, Signal, Slot
from construct import *
from construct.lib import *


class UDPParser(QObject):

    message = Signal(dict)
    
    messageformat = Struct(
     "sensor_id" / Int16ul,
     "sequence_id" / Int16ul,
     "data_format" / Int16ul,
     "data_size" / Int16ul,
     "data" / Bytes(this.data_size))

    def __init__(self):
        QObject.__init__(self)

#    @Slot()
#    def start(self):
        
    @Slot()
    def parse(self, timestamp, msg):
        try:
            tempdict = self.messageformat.parse(msg)
        except StreamError as err:
            pass
        else:
            
            tempdict['timestamp'] = timestamp
            self.message.emit(tempdict)
            # print(tempdict)
