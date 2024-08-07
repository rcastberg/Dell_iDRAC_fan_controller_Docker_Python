#!/usr/bin/env python3
import requests
import os

import signal
import sys
import time
from datetime import datetime
from collections import deque
from pysnmp.hlapi import *
import logging
from logging import getLogger, ERROR, CRITICAL, WARNING, INFO, DEBUG

# Enable default logging
logging.basicConfig(level = logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)
logger.setLevel("INFO")

def signal_handler(sig, frame):
    logger.error('You pressed Ctrl+C!')
    # Reset fan control to Dell default
    apply_Dell_fan_control_profile()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def load_env_default(env_var, default):
    try:
        variable = os.environ[env_var]
    except KeyError:
        variable = default
        warn_message =f"Environment variable {env_var} not set, using default value: {default}"
        logger.warning(warn_message)
    return variable

debug_level = load_env_default('DEBUG_LEVEL', 'ERROR')
logger.error(f"Setting log level to {debug_level}")
logger.setLevel(debug_level)

hostname=load_env_default('IDRAC_HOST', 'localhost')
gpu_host=load_env_default('GPU_HOST', hostname)
gpu_port=load_env_default('GPU_PORT', '980')
hysterisis_length=int(load_env_default('HYSTERISIS_LENGTH', '10'))
STEP_PERCENT=int(load_env_default('STEP_PERCENT', '2'))
check_interval=int(load_env_default('CHECK_INTERVAL', 5))
third_party_pcie_cooling=load_env_default('THIRD_PARTY_PCIE_COOLING', 'True')

USE_SNMP=load_env_default('USE_SNMP', 'False')
SNMP_COMMUNITY=load_env_default('SNMP_COMMUNITY', 'public')

#Get parameters for CPU/TEMP Curves
CPU_Curve=os.getenv("CPU_Curve","pow(10,((temp-10)/20))")
GPU_Curve=os.getenv("GPU_Curve","pow(10,((temp-18)/20))")
MIN_FAN_SPEED=int(os.getenv("MIN_FAN",10))
DELL_Control=int(os.getenv("DELL_Control",70))
IDRAC_LOGIN_STRING = f"lanplus -H {hostname} -U {load_env_default('IDRAC_USERNAME', 'root')} -P {load_env_default('IDRAC_PASSWORD', 'Password')}"

fan_his = deque([10]*10, maxlen=10)

def get_temp_gpu(gpu_hostname, port):
    if gpu_hostname == "False":
        return 0
    else:
      url = f"http://{gpu_hostname}:{gpu_port}/"
      try:
          response = requests.get(url)
          if response.status_code == 200:
              return int(response.text.strip())
          else:
              return 999
      except Exception as e:
          return 999

#Use ipmitool to get the temperature of the iDRAC
#Get the Inlet, Exhaust, and CPU temperatures
def get_temp_idrac():
    temp_data = os.popen(f"ipmitool -I {IDRAC_LOGIN_STRING} sdr type temperature").read()
    #Split temperatures into a dictionary
    temp_data = temp_data.split('\n')
    # Itteratre though, Inlet, Exhaust, and CPU temperatures and add to dictionary
    # Output is in the format:
    # Inlet Temp       | 04h | ok  |  7.1 | 27 degrees C
    temp_dict = {}
    for temp in temp_data:
        if "Inlet" in temp:
            temp_dict['Inlet'] = int(temp.split('|')[4].split()[0])
        elif "Exhaust" in temp:
            temp_dict['Exhaust'] = int(temp.split('|')[4].split()[0])
    # The CPU temperatures are stored using the same key in temp_data called Temp, store each as a new cpu key in temp_dict
    cpu_temps = [temp for temp in temp_data if temp.startswith('Temp')]
    for i, temp in enumerate(cpu_temps):
        temp_dict[f'CPU{i}'] = int(temp.split('|')[4].split()[0])
    return temp_dict


def third_party_PCIe_card_Dell_default_cooling_response(enable=True):
    # We could check the current cooling response before applying but it's not very useful so let's skip the test and apply directly
    if enable:
        enable_string = '0x01'
    else:
        enable_string = '0x00'
    os.popen(' '.join(['ipmitool', '-I', IDRAC_LOGIN_STRING, 'raw', '0x30', '0xce', '0x00', '0x16', '0x05', '0x00', '0x00', '0x00', '0x05', '0x00', enable_string, '0x00', '0x00']))


def apply_Dell_fan_control_profile():
    # Use ipmitool to send the raw command to set fan control to Dell default
    logger.info("Swtich to DELL fan control profile...")
    os.popen(' '.join(['ipmitool', '-I', IDRAC_LOGIN_STRING, 'raw', '0x30', '0x30', '0x01', '0x01']))

def apply_user_fan_control_profile(decimal_fan_speed):
    # Use ipmitool to send the raw command to set fan control to user-specified value
    HEXADECIMAL_FAN_SPEED = '0x{:02x}'.format(decimal_fan_speed)
    os.popen(' '.join(['ipmitool', '-I', IDRAC_LOGIN_STRING, 'raw', '0x30', '0x30', '0x01', '0x00']))
    os.popen(' '.join(['ipmitool', '-I', IDRAC_LOGIN_STRING, 'raw', '0x30', '0x30', '0x02', '0xff', HEXADECIMAL_FAN_SPEED]))
    return decimal_fan_speed


def print_headers():
    #Loop to check the temperature of the iDRAC with delay set by check_interval
    logger.info("")
    logger.info(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):19}    ------- Temperatures ------------")
    logger.info("    Elapsed time      Inlet  CPU 1  CPU 2  GPU  Exhaust          Active fan speed profile          3rd PCIe card Dell default   Comment")
    logger.info("                                                                                                       cooling response")

def set_target_fan_speed(CPU0_temp, CPU1_temp, GPU_temp, force=False):
    if CPU0_temp > DELL_Control or CPU1_temp > DELL_Control:
        apply_Dell_fan_control_profile()
        return "Dell Fan Control"
    FanCPU0 = int(eval(CPU_Curve.replace('temp','CPU0_temp')))
    FanCPU1 = int(eval(CPU_Curve.replace('temp','CPU1_temp')))
    FanGPU =  int(eval(GPU_Curve.replace('temp','GPU_temp')))
    current_fanspeed = max(FanCPU0, FanCPU1, FanGPU, MIN_FAN_SPEED)
    # Apply only if different by more than STEP_PERCENT since previous apply

    if abs(fan_his[-1]-current_fanspeed)>STEP_PERCENT:
        fan_his.append(current_fanspeed)
        apply_user_fan_control_profile(max(fan_his))
        return f"User fan control set to {max(fan_his)}", f"C0:{FanCPU0},C1:{FanCPU1},G0:{FanGPU},HA:{sum(fan_his)/hysterisis_length:.0f},HM:{max(fan_his)}"
    else:
        fan_his.append(fan_his[-1])
        if force:
            apply_user_fan_control_profile(max(fan_his))
            return f"User fan control forced ({max(fan_his)})", f"C0:{FanCPU0},C1:{FanCPU1},G0:{FanGPU},HA:{sum(fan_his)/hysterisis_length:.0f},HM:{max(fan_his)}"
        else:
            return f"User fan control unchanged ({max(fan_his)})", f"C0:{FanCPU0},C1:{FanCPU1},G0:{FanGPU},HA:{sum(fan_his)/hysterisis_length:.0f},HM:{max(fan_his)}"


SNMP_Sensors = {
    '1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.1':{'name':'Inlet', 'divisor':10, 'int':True},
    '1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.2':{'name':'Exhaust', 'divisor':10, 'int':True},
    '1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.3':{'name':'CPU0', 'divisor':10, 'int':True},
    '1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.4':{'name':'CPU1', 'divisor':10, 'int':True},
    '1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.1':{'name':'FAN1', 'divisor':1, 'int':True},
    '1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.2':{'name':'FAN2', 'divisor':1, 'int':True},
    '1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.3':{'name':'FAN3', 'divisor':1, 'int':True},
    '1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.4':{'name':'FAN4', 'divisor':1, 'int':True},
    '1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.5':{'name':'FAN5', 'divisor':1, 'int':True},
    '1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.6':{'name':'FAN6', 'divisor':1, 'int':True},
}


def get_snmp_data(oid, ip, community):
    iterator = getCmd(
        SnmpEngine(),
        CommunityData(community),
        UdpTransportTarget((ip, 161)),
        ContextData(),
        ObjectType(ObjectIdentity(oid))
    )

    errorIndication, errorStatus, errorIndex, varBinds = next(iterator)

    if errorIndication:
        logger.error(f'Error: {errorIndication}')
        return None
    elif errorStatus:
        logger.error(f'Error: {errorStatus.prettyPrint()} at {errorIndex and varBinds[int(errorIndex) - 1][0] or "?"}')
        return None
    else:
        for varBind in varBinds:
            return varBind[1].prettyPrint()

def get_sensor_data(host, community, sensors):
    return_data = {}
    for oid in sensors:
        value = get_snmp_data(oid, host, community)
        if value and sensors[oid]['divisor'] is not None  and sensors[oid]['int'] is True:
            return_data[sensors[oid]["name"]]=int(float(value)/sensors[oid]['divisor'])
        elif value and sensors[oid]['divisor'] is not None:
            return_data[sensors[oid]["name"]]=float(value)/sensors[oid]['divisor']
        elif value:
            return_data[sensors[oid]["name"]]=value
        else:
            logger.error('Failed to retrieve SNMP data.')
    return return_data

i=-1
cur_time = datetime.now()
# Set third party PCIe card cooling to user choice
third_party_PCIe_card_Dell_default_cooling_response(third_party_pcie_cooling == 'True')
logger.info('Initialized, press Ctrl+C to exit')
while True:
    i+=1
    if USE_SNMP == "True":
        temp_dict = get_sensor_data(hostname, SNMP_COMMUNITY, SNMP_Sensors)
        if 'FAN1' in temp_dict:
            avg_fan_speed =[temp_dict[i] for i in temp_dict if 'FAN' in i]
            avg_fan_speed = int(sum(avg_fan_speed)/len(avg_fan_speed))
    else:
        temp_dict = get_temp_idrac()
        avg_fan_speed = 'NaN'
    gpu_temp = get_temp_gpu(gpu_host, gpu_port)
    prev_time = cur_time
    cur_time = datetime.now()
    elapsed_time = int((cur_time - prev_time).total_seconds())
    # Print temperatures, active fan control profile and comment if any change happened during last time interval
    if i % 10 == 0:
        print_headers()
        i=0
        fan_info,deep_info = set_target_fan_speed(temp_dict['CPU0'], temp_dict['CPU1'], gpu_temp, force=True)
    else:
        fan_info,deep_info = set_target_fan_speed(temp_dict['CPU0'], temp_dict['CPU1'], gpu_temp)
    deep_info = deep_info + ',FA:'+str(avg_fan_speed)
    logger.info(f"{elapsed_time:18}s  {temp_dict['Inlet']:3}°C  {temp_dict['CPU0']:3}°C  {temp_dict['CPU1']:3}°C   {gpu_temp:3}°C  {temp_dict['Exhaust']:3}°C    {fan_info:38}  {third_party_pcie_cooling:21}  {deep_info}")

    time.sleep(check_interval)
