
from struct import unpack
import numpy as np

class emRadParser():
 
    def __init__(self):
        pass
    

    def parse(self, data):
        try:
            temp = np.reshape(unpack('<256i', data), (64,4))
            return temp
        except:
            pass
