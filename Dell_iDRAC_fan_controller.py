#!/usr/bin/env python3
import requests
import os
from dotenv import load_dotenv
load_dotenv()

import signal
import sys
import time
from datetime import datetime

def signal_handler(sig, frame):
    print('You pressed Ctrl+C!')
    # Reset fan control to Dell default
    apply_Dell_fan_control_profile()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


hostname=os.getenv('IDRAC_HOST', 'localhost')
port=os.getenv('IDRAC_PORT', '8080')
gpu_host=os.getenv('GPU_HOST', hostname)
gpu_port=os.getenv('GPU_PORT', '980')
check_interval=int(os.getenv('CHECK_INTERVAL', 5))
third_party_pcie_cooling=os.getenv('THIRD_PARTY_PCIE_COOLING', 'True')

#Get parameters for CPU/TEMP Curves
CPU_Curve=os.getenv("CPU_Curve","(30,10),(60,100)")
GPU_Curve=os.getenv("GPU_Curve","(40,30),(60,100)")
DELL_Control=int(os.getenv("DELL_Control",70))
IDRAC_LOGIN_STRING = f"lanplus -H {os.environ['IDRAC_HOST']} -U {os.environ['IDRAC_USERNAME']} -P {os.environ['IDRAC_PASSWORD']}"


def get_temp_gpu(hostname, port):
    url = f"http://{gpu_host}:{gpu_port}/"
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


import subprocess

def apply_Dell_fan_control_profile():
    # Use ipmitool to send the raw command to set fan control to Dell default
    print("Swtich to DELL fan control profile...")
    print(['ipmitool', '-I', IDRAC_LOGIN_STRING, 'raw', '0x30', '0x30', '0x01', '0x01'])
    os.popen(' '.join(['ipmitool', '-I', IDRAC_LOGIN_STRING, 'raw', '0x30', '0x30', '0x01', '0x01']))


def apply_user_fan_control_profile(decimal_fan_speed):
    # Use ipmitool to send the raw command to set fan control to user-specified value
    HEXADECIMAL_FAN_SPEED = '0x{:02x}'.format(decimal_fan_speed)
    os.popen(' '.join(['ipmitool', '-I', IDRAC_LOGIN_STRING, 'raw', '0x30', '0x30', '0x01', '0x00']))
    os.popen(' '.join(['ipmitool', '-I', IDRAC_LOGIN_STRING, 'raw', '0x30', '0x30', '0x02', '0xff', HEXADECIMAL_FAN_SPEED]))
    return decimal_fan_speed


def print_headers():
    #Loop to check the temperature of the iDRAC with delay set by check_interval
    print("")
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):19}    ------- Temperatures ------------")
    print("    Elapsed time      Inlet  CPU 1  CPU 2  GPU  Exhaust          Active fan speed profile          3rd PCIe card Dell default   Comment")
    print("                                                                                                       cooling response")

def set_target_fan_speed(CPU0_temp, CPU1_temp, GPU_temp):
    if CPU0_temp > DELL_Control or CPU1_temp > DELL_Control:
        apply_Dell_fan_control_profile()
        return "Dell Fan Control"
    (x1,y1,x2,y2) = [int(v) for v in CPU_Curve.replace('(','').replace(')','').split(",")]
    CPU_gradient = (y2 - y1) / (x2 - x1)
    CPU_intercept = y1 - CPU_gradient * x1
    FanCPU0 = int(CPU0_temp*CPU_gradient + CPU_intercept)
    FanCPU1 = int(CPU1_temp*CPU_gradient + CPU_intercept)
    (x1,y1,x2,y2) = [int(v) for v in GPU_Curve.replace('(','').replace(')','').split(",")]
    GPU_gradient = (y2 - y1) / (x2 - x1)
    GPU_intercept = y1 - GPU_gradient * x1
    FanGPU = int(GPU_temp*GPU_gradient + GPU_intercept)
    apply_user_fan_control_profile(max(FanCPU0, FanCPU1, FanGPU))
    return "User fan control set to {}%".format(max(FanCPU0, FanCPU1, FanGPU)), (FanCPU0, FanCPU1, FanGPU)

i=-1
cur_time = datetime.now()
# Set third party PCIe card cooling to user choice
third_party_PCIe_card_Dell_default_cooling_response(third_party_pcie_cooling == 'True')
while True:
    i+=1
    temp_dict = get_temp_idrac()
    gpu_temp = get_temp_gpu(gpu_host, gpu_port)
    prev_time = cur_time
    cur_time = datetime.now()
    elapsed_time = int((cur_time - prev_time).total_seconds())
    # Print temperatures, active fan control profile and comment if any change happened during last time interval
    if i % 10 == 0:
        print_headers()
        i=0
    fan_info,deep_info = set_target_fan_speed(temp_dict['CPU0'], temp_dict['CPU1'], gpu_temp)
    print(f"{elapsed_time:18}s  {temp_dict['Inlet']:3}°C  {temp_dict['CPU0']:3}°C  {temp_dict['CPU1']:3}°C   {gpu_temp:3}°C  {temp_dict['Exhaust']:3}°C    {fan_info:38}  {third_party_pcie_cooling:21}  {deep_info}")

    time.sleep(check_interval)