"""
Crazyflie 101 Tutorial - 1_fwd_bwd_V2.py
Author: Guy Maalouf
Date: May 12, 2023
"""
import sys
import os
import time
import logging
import struct
import socket
import select
import numpy as np
from threading import Thread
from threading import Event

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.positioning.motion_commander import MotionCommander
from cflib.utils import uri_helper

#Vicon
#Vicon real positions
VICON_POS = {'X':0,'Y':0,'Z':0,'Pitch':0,'Roll':0,'Yaw':0}

#Vicon take_off pos
VICON_INITIALIZED = 0
VICON_POS_INIT = {'X':0,'Y':0,'Z':0,'Pitch':0,'Roll':0,'Yaw':0}

#Vicon relative pos
VICON_POS_REL = {'X':0,'Y':0,'Z':0,'Pitch':0,'Roll':0,'Yaw':0}

class ViconUDPDataRelay(Thread):
    def __init__(self, RX_sock):
        Thread.__init__(self)
        self.DEBUG = False
        # Define Message length
        self.MsgLen = 1024
        self.RX_sock = RX_sock
        self.MessageRX_flag = False
        self.SrvMsgReceived = True
        self.RxMessage = None
        # Entry dictionary
        self.object_dict = {}
        self.reset_object_dict()
        
    def reset_object_dict(self):
        self.object_dict['number_objects'] = 0

    def ReceiveMsgOverUDP(self):
        Header = 'Waiting!'
        # Select RX_sock
        sock = self.RX_sock
        # Verify if data has been received from VICON
        ready = select.select([sock], [], [], 0.001)
        # If data has been received, process it
        if ready[0]:
            # Receive message. Buffer size defined by 'MsgLen'
            self.MessageRX_flag = True
            data, addr = sock.recvfrom(self.MsgLen)
            # Extract message header
            Sequence_B00 = data[0]
            Sequence_B01 = data[1]
            Sequence_B02 = data[2]
            Sequence_B03 = data[3]
            Sequence = (Sequence_B03<<32)+(Sequence_B02<<16)+(Sequence_B01<<8)+Sequence_B00
            self.ProcessViconData(data[0:160])

    def ProcessViconData(self, data):
        # Create struct with message format:
        # Data types according to https://docs.python.org/3/library/struct.html
        # FrameNumber                       -> B000 - B003 (uint32,  I)
        # ItemsInBlock                      -> B004        (uint8,   B)
        #              -----------------------------------------------
        #                      ItemID       -> B005        (uint8,   B)
        #              Header  ItemDataSize -> B006 - B007 (uint16,  H)
        #                      ItemName     -> B008 - B031 (uint8,   B)
        #              -----------------------------------------------
        # Item_raw_00          TransX       -> B032 - B039 (double,  d)
        #                      TransY       -> B040 - B047 (double,  d)
        #                      TransZ       -> B048 - B055 (double,  d)
        #              Data    RotX         -> B056 - B063 (double,  d)
        #                      RotY         -> B064 - B071 (double,  d)
        #                      RotZ         -> B072 - B079 (double,  d)    
        #              -----------------------------------------------
        #                      ItemID       -> B080        (uint8,   B)
        #              Header  ItemDataSize -> B081 - B082 (uint16,  H)
        #                      ItemName     -> B083 - B106 (uint8,   B)
        #              -----------------------------------------------
        # Item_raw_01          TransX       -> B107 - B114 (double,  d)
        #                      TransY       -> B115 - B122 (double,  d)
        #                      TransZ       -> B123 - B130 (double,  d)
        #              Data    RotX         -> B131 - B139 (double,  d)
        #                      RotY         -> B140 - B146 (double,  d)
        #                      RotZ         -> B147 - B154 (double,  d)    
        #              -----------------------------------------------
        s = struct.Struct('I2BH24c6dBH24c6d')
        UnpackedData = s.unpack(data)
        FrameNumber  = UnpackedData[0]
        ItemsInBlock = UnpackedData[1]
        Item_raw_00_ItemID       = UnpackedData[2]
        Item_raw_00_ItemDataSize = UnpackedData[3]
        Item_raw_00_ItemName     = UnpackedData[4:28]
        Item_raw_00_TransX       = UnpackedData[28]
        Item_raw_00_TransY       = UnpackedData[29]
        Item_raw_00_TransZ       = UnpackedData[30]
        Item_raw_00_RotX         = UnpackedData[31]
        Item_raw_00_RotY         = UnpackedData[32]
        Item_raw_00_RotZ         = UnpackedData[33]
        Item_raw_00_ItemDataSize_string = []
        for this_byte in range(0,len(Item_raw_00_ItemName)):
            if Item_raw_00_ItemName[this_byte]>= b'!' and Item_raw_00_ItemName[this_byte]<= b'~':
                Item_raw_00_ItemDataSize_string.append(Item_raw_00_ItemName[this_byte].decode('utf-8'))
        Item_raw_00_ItemDataSize_string = ''.join(Item_raw_00_ItemDataSize_string)     
        self.object_dict[Item_raw_00_ItemDataSize_string] = {'PosX':Item_raw_00_TransX,'PosY':Item_raw_00_TransY,
                                                             'PosZ':Item_raw_00_TransZ,'RotX':Item_raw_00_RotX,
                                                             'RotY':Item_raw_00_RotY,'RotZ':Item_raw_00_RotZ}
        self.object_dict['number_objects'] += 1
        
        #Store vicon readings in global variables
        #Vicon real positions
        global VICON_POS, VICON_POS_INIT, VICON_POS_REL, VICON_INITIALIZED

        # Storing values in VICON_POS (vicon position)
        VICON_POS['X'] = self.object_dict[Item_raw_00_ItemDataSize_string]['PosX']*1e-1
        VICON_POS['Y']  = self.object_dict[Item_raw_00_ItemDataSize_string]['PosY']*1e-1
        VICON_POS['Z']  = self.object_dict[Item_raw_00_ItemDataSize_string]['PosZ']*1e-1
        VICON_POS['Pitch']  = np.rad2deg(self.object_dict[Item_raw_00_ItemDataSize_string]['RotY'])
        VICON_POS['Roll']  = np.rad2deg(self.object_dict[Item_raw_00_ItemDataSize_string]['RotX'])
        VICON_POS['Yaw']  = np.rad2deg(self.object_dict[Item_raw_00_ItemDataSize_string]['RotZ'])
        
        #If not initialised, initialise VICON_POS_INIT (initial vicon position, take off point)
        if VICON_INITIALIZED == 0:
            VICON_INITIALIZED = 1
            VICON_POS_INIT['X'] = VICON_POS['X']
            VICON_POS_INIT['Y'] = VICON_POS['Y']
            VICON_POS_INIT['Z'] = VICON_POS['Z']
            VICON_POS_INIT['Pitch'] = VICON_POS['Pitch']
            VICON_POS_INIT['Roll'] = VICON_POS['Roll']
            VICON_POS_INIT['Yaw'] = VICON_POS['Yaw']

        #Find relative position of drone compared to home point
        VICON_POS_REL['X'] = VICON_POS['X'] - VICON_POS_INIT['X']
        VICON_POS_REL['Y'] = VICON_POS['Y'] - VICON_POS_INIT['Y']
        VICON_POS_REL['Z'] = VICON_POS['Z'] - VICON_POS_INIT['Z']
        VICON_POS_REL['Ptch'] = VICON_POS['Pitch'] - VICON_POS_INIT['Pitch']
        VICON_POS_REL['Roll'] = VICON_POS['Roll'] - VICON_POS_INIT['Roll']
        VICON_POS_REL['Yaw'] = VICON_POS['Yaw'] - VICON_POS_INIT['Yaw']

        if self.DEBUG:
            #
            print('\tPosition [cm]: {0:+3.4f}, {1:+3.4f}, {2:+3.4f}'.format(VICON_POS_REL['X'],VICON_POS_REL['Y'],VICON_POS_REL['Z']))
            print('\tAttitude [deg]: {0:+3.4f}, {1:+3.4f}, {2:+3.4f}'.format(VICON_POS_REL['Roll'],VICON_POS_REL['Pitch'],VICON_POS_REL['Yaw']))
            print('----------------------------------')
        
    def close(self):
        #
        pass

def vicon_update():
    try:
        MyViconDataRelay.ReceiveMsgOverUDP()
        
    except(KeyboardInterrupt,SystemExit):
        print("\nClosing program ...")
        RX_sock.close() # Close socket
        sys.exit() # Exit program
    
    except socket.error as msg:
        print("Socket error!")
        RX_sock.close() # Close socket
        print(msg)
        sys.exit()

#Crazyflie
URI = uri_helper.uri_from_env(default='radio://0/80/2M/E7E7E7E7E7')

DEFAULT_HEIGHT = 0.5
BOX_LIMIT = 0.5

deck_attached_event = Event()

logging.basicConfig(level=logging.ERROR)

position_estimate = [0, 0]

def fwd_bwd_vicon(scf):
    global VICON_POS_REL,VICON_POS_REL

    with MotionCommander(scf, default_height=DEFAULT_HEIGHT) as mc:
        BOX_LIMIT = 0.5
        while (1):
            print("VICON X REL:", VICON_POS_REL['X'])
            vicon_update()
            if VICON_POS_REL['X'] > BOX_LIMIT:
                mc.start_back()
            elif VICON_POS_REL['X'] < -BOX_LIMIT:
                mc.start_forward()

            time.sleep(0.1)

def log_pos_callback(timestamp, data, logconf):
    print(data)
    global position_estimate
    position_estimate[0] = data['stateEstimate.x']
    position_estimate[1] = data['stateEstimate.y']

def param_deck_flow(_, value_str):
    value = int(value_str)
    print(value)
    if value:
        deck_attached_event.set()
        print('Deck is attached!')
    else:
        print('Deck is NOT attached!')

#Main
if __name__ == "__main__":
    IP_Address01 = "0.0.0.0"
    Host01   = (IP_Address01, 51001)
    # Create RX socket
    RX_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    RX_sock.bind(Host01)
    MyViconDataRelay = ViconUDPDataRelay(RX_sock)
    MyViconDataRelay.DEBUG = True
    
    cflib.crtp.init_drivers()

    with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
       
        scf.cf.param.add_update_callback(group='deck', name='bcFlow2',
                                         cb=param_deck_flow)
        time.sleep(1)

        logconf = LogConfig(name='Position', period_in_ms=10)
        logconf.add_variable('stateEstimate.x', 'float')
        logconf.add_variable('stateEstimate.y', 'float')
        scf.cf.log.add_config(logconf)
        logconf.data_received_cb.add_callback(log_pos_callback)

        if not deck_attached_event.wait(timeout=5):
            print('No flow deck detected!')
            sys.exit(1)
         #Check vicon connected before takeoff
        while VICON_INITIALIZED == 0:
            vicon_update()
            print('Waiting to connect to vicon ... \n')

        fwd_bwd_vicon(scf)

    

    
