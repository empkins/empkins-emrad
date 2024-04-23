
from struct import unpack
import numpy as np

class emRadParser():
 
    def __init__(self):
        pass
    

    def parse(self, data):
        try:
            temp = np.reshape(unpack('<320i', data), (32,10))
            return temp
        except:
            pass
