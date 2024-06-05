#!/usr/bin/env python3
import requests
import os

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

def load_env_default(env_var, default):
    try:
        variable = os.environ[env_var]
    except KeyError:
        variable = default
        print(f"Environment variable {env_var} not set, using default value: {default}")
    return variable

hostname=load_env_default('IDRAC_HOST', 'localhost')
gpu_host=load_env_default('GPU_HOST', hostname)
gpu_port=load_env_default('GPU_PORT', '980')
check_interval=int(load_env_default('CHECK_INTERVAL', 5))
third_party_pcie_cooling=load_env_default('THIRD_PARTY_PCIE_COOLING', 'True')

#Get parameters for CPU/TEMP Curves
CPU_Curve=os.getenv("CPU_Curve","pow(10,((temp-10)/20))")
GPU_Curve=os.getenv("GPU_Curve","pow(10,((temp-18)/20))")
MIN_FAN_SPEED=int(os.getenv("MIN_FAN",10))
DELL_Control=int(os.getenv("DELL_Control",70))
IDRAC_LOGIN_STRING = f"lanplus -H {hostname} -U {load_env_default('IDRAC_USERNAME', 'root')} -P {load_env_default('IDRAC_PASSWORD', 'Password')}"


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
    FanCPU0 = int(eval(CPU_Curve.replace('temp','CPU0_temp')))
    FanCPU1 = int(eval(CPU_Curve.replace('temp','CPU1_temp')))
    FanGPU =  int(eval(GPU_Curve.replace('temp','GPU_temp')))
    apply_user_fan_control_profile(max(FanCPU0, FanCPU1, FanGPU, MIN_FAN_SPEED))
    return "User fan control set to {}%".format(max(FanCPU0, FanCPU1, FanGPU, MIN_FAN_SPEED)), (FanCPU0, FanCPU1, FanGPU)

i=-1
cur_time = datetime.now()
# Set third party PCIe card cooling to user choice
third_party_PCIe_card_Dell_default_cooling_response(third_party_pcie_cooling == 'True')
print('Initialized, press Ctrl+C to exit')
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