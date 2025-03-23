# RUN USING: python3 dcgmReaderToVictoriaMetrics.py

# Copyright (c) 2024, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from DcgmReader import *
import dcgm_fields
import time
import docker
import os
import argparse
import sys
import socket
import re
import requests
import gzip
from datetime import datetime, timezone
from dotenv import load_dotenv
load_dotenv()

# sending telemetry to Victoria Metrics database
vm_url = os.getenv('VM_URL')
write_endpoint = "/api/v2/write" # this is the InfluxDB line protocol endpoint
precision = 'ms' # precision for time --> TODO: ms for now
vm_write_url = f"{vm_url}{write_endpoint}?precision={precision}" 

# TODO: potentially use authentication (more secure)
# vm_user = os.getenv('VM_USER')
# vm_password = os.getenv('VM_PASSWORD')
# authentication = (vm_user, vm_password)
authentication = None

# connection status
vm_connected = False

# try to connect to Victoria Metrics endpoint
def test_vm_connection():
    try:
        response = requests.get(f"{vm_url}/health", auth=authentication, timeout=10)
        print("IN TEST_VM_CONNECTION TRY")
        if response.status_code == 200:
            print("Successfully connected to Victoria Metrics")
            return True
        else:
            print(f"Connection to Victoria Metrics failed with status code: {response.status_code} --> {response.text}")
            return False
        
    except Exception as e:
        print(f"Error connecting to Victoria Metrics: {str(e)}")
        return False
        
vm_connected = test_vm_connection()

# function to send batched data to Victoria Metrics with gzip compression
def send_data_to_vm(lines):
    global vm_connected
    
    if not lines:
        return False
    
    try:
        # join all the metrics
        entire_payload = "\n".join(lines)
        
        print("entire payload")
        print(entire_payload)
        
        # compress payload with gzip
        compressed_payload = gzip.compress(entire_payload.encode('utf-8'))
        
        # send with headers
        headers = {
            'Content-Type': 'text/plain',
            'Content-Encoding': 'gzip'
        }
        
        # send request
        response = requests.post(
            vm_write_url,
            data=compressed_payload,
            headers=headers,
            auth=authentication,
            timeout=10
        )
        
        if response.status_code < 400:
            print("Successfully sent data to Victoria Metrics")
            return True
        else:
            print("Did not successfully send data to Victoria Metrics")
            print(f"{response.status_code} --> {response.text}")
            vm_connected = False # disconnect bcs didn't successfully connect
            return False
        
    except Exception as e:
        print(f"Error sending data to Victoria Metrics: {str(e)}")
        vm_connected = False # disconnect bcs didn't successfully connect
        return False
        

fieldsToGrab = [
    dcgm_fields.DCGM_FI_DEV_NAME,
    dcgm_fields.DCGM_FI_DEV_BRAND,
    dcgm_fields.DCGM_FI_DEV_SERIAL,
    dcgm_fields.DCGM_FI_DEV_UUID,
    dcgm_fields.DCGM_FI_DEV_POWER_USAGE,
    dcgm_fields.DCGM_FI_DEV_GPU_TEMP,
    dcgm_fields.DCGM_FI_DEV_MEM_CLOCK,
    dcgm_fields.DCGM_FI_DEV_MEMORY_TEMP,
    dcgm_fields.DCGM_FI_DEV_POWER_USAGE_INSTANT,
    dcgm_fields.DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION,
    dcgm_fields.DCGM_FI_DEV_MEM_COPY_UTIL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL,
    dcgm_fields.DCGM_FI_DEV_PCIE_TX_THROUGHPUT,
    dcgm_fields.DCGM_FI_DEV_PCIE_RX_THROUGHPUT,
    # in newest version (4.0) this one is deprecated, it should be DCGM_FI_DEV_CLOCKS_EVENT_REASONS
    dcgm_fields.DCGM_FI_DEV_CLOCK_THROTTLE_REASONS,
    dcgm_fields.DCGM_FI_DEV_SM_CLOCK,
    dcgm_fields.DCGM_FI_DEV_GPU_UTIL,
    dcgm_fields.DCGM_FI_DEV_RETIRED_PENDING,
    dcgm_fields.DCGM_FI_DEV_RETIRED_SBE,
    dcgm_fields.DCGM_FI_DEV_RETIRED_DBE,
    dcgm_fields.DCGM_FI_DEV_ECC_SBE_VOL_TOTAL,
    dcgm_fields.DCGM_FI_DEV_ECC_DBE_VOL_TOTAL,
    dcgm_fields.DCGM_FI_DEV_ECC_SBE_AGG_TOTAL,
    dcgm_fields.DCGM_FI_DEV_ECC_DBE_AGG_TOTAL,
    dcgm_fields.DCGM_FI_DEV_PCIE_REPLAY_COUNTER,
    dcgm_fields.DCGM_FI_DEV_POWER_VIOLATION,
    dcgm_fields.DCGM_FI_DEV_THERMAL_VIOLATION,
    dcgm_fields.DCGM_FI_DEV_XID_ERRORS,
    dcgm_fields.DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_CRC_DATA_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL,
    dcgm_fields.DCGM_FI_DEV_FB_TOTAL,   # framebuffer total
    dcgm_fields.DCGM_FI_DEV_FB_FREE,    # framebuffer free
    dcgm_fields.DCGM_FI_DEV_FB_USED,    # framebuffer used
    dcgm_fields.DCGM_FI_DEV_FB_RESERVED # framebuffer reserved
]

class DataHandlerReader(DcgmReader):
    '''
        Override just this method to handle the entire map of data in your own way. This 
        might be used if you want to iterate by field id and then GPU or something like that.
        This method is called once for each time the Process() method is invoked.
    '''
    def CustomDataHandler(self, fvs):
        for fieldId in self.m_publishFieldIds:
            if fieldId in self.m_dcgmIgnoreFields:
                continue
        
            out = 'Values for %s:' % (self.m_fieldIdToInfo[fieldId].tag)
            wasBlank = True
            for gpuId in list(fvs.keys()):
                gpuFv = fvs[gpuId]
                val = gpuFv[fieldId][-1]

                # Skip blank values. Otherwise, we'd have to insert a placeholder blank value based on the fieldId
                if val.isBlank:
                    continue

                wasBlank = False
                append = " GPU%d=%s" % (gpuId, val.value)
                out = out + append

            if wasBlank == False:
                print(out)

'''
    hostname         : Port for the nv-hostengine (port 0000:5555)
    field_ids        : List of the field ids to publish. If it isn't specified, our default list is used.
    update_frequency : Frequency of update in microseconds. Defauls to 10 seconds or 10000000 microseconds
    keep_time        : Max time to keep data from NVML, in seconds. Default is 3600.0 (1 hour)
    ignores          : List of the field ids we want to query but not publish.
'''
def DcgmReaderDictionary(hostname, field_ids, update_frequency, keep_time, ignores, field_groups):
    global vm_connected
    
    try:
        # Instantiate a DcgmReader object
        dr = DcgmReader(
            hostname=hostname, 
            fieldIds=field_ids, 
            updateFrequency=update_frequency, 
            maxKeepAge=keep_time, 
            ignoreList=ignores, 
            fieldGroupName=field_groups
        )

        # Get the default list of fields as a dictionary of dictionaries:
        # gpuId -> field name -> field value
        data = dr.GetLatestGpuValuesAsFieldNameDict()
        if not data:
            print("No data received from dcgm :(")
            return
        
        # get line protocol strings to batch send
        lines = []
        
        for gpuId, gpuData in data.items():
            gpu_uuid = gpuData.get("uuid", None)
            # print("gpu_uuid: ", gpu_uuid)
            if gpu_uuid is None:
                # UUID is missing --> error
                print(f"UUID is missing for GPU {gpuId}")
                continue
            
            try:
                clientId = getClientId()
                
                # prep GPU data entry with line protocol
                # format: <measurement>,<tags> <fields> 
                measurement = gpu_uuid
                
                tags = f"clientId={clientId}"
                
                # store name and brand as tags
                if "name" in gpuData and gpuData["name"] not in [None, "", "N/A"]:
                    name_value = str(gpuData["name"]).replace(" ","\\ ").replace(",","\\,").replace("=","\\=")
                    tags += f",name={name_value}"
                if "brand" in gpuData and gpuData["brand"] not in [None, "", "N/A"]:
                    brand_value = str(gpuData["name"]).replace(" ","\\ ").replace(",","\\,").replace("=","\\=")
                    tags += f",brand={brand_value}"
                    
                # collect field data
                fields = []
                
                # store all metrics inside 'fields'
                for fieldName, latest_value, in gpuData.items():
                    if fieldName in ["uuid", "name", "brand"] or latest_value in [None, "", "N/A"]:
                        continue
                    
                    try:
                        # try to convert numerical strings to accepted type
                        if isinstance(latest_value, str):
                            if latest_value.replace('.', '', 1).isdigit():
                                if '.' in latest_value:
                                    latest_value = float(latest_value)
                                else:
                                    latest_value = int(latest_value)
                                    
                        # append to fields set
                        fields.append(f"{fieldName}={latest_value}")
                    except (ValueError, TypeError):
                        # otherwise, keep as string (should all be nums though)
                        fields.append(f"{fieldName}={str(latest_value)}")
                            
                # Compute FB_UTIL (Framebuffer Utilization)
                fb_used = gpuData.get("fb_used")
                fb_total = gpuData.get("fb_total")

                # print(f"fb_util Calculated: ", (100 * round(fb_used / fb_total, 2)))
                if fb_used is not None and fb_total not in [None, 0]:  # Avoid division by zero
                    fb_used = float(fb_used) if isinstance(fb_used, str) else fb_used
                    fb_total = float(fb_total) if isinstance(fb_total, str) else fb_total
                    
                    fb_util = 100 * (fb_used / fb_total)
                    fields.append(f"fb_util={round(fb_util, 2)}") # Store as percentage (rounded)
                    
                if fields:
                    # # set timestamp
                    # timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
                    
                    line = f"{measurement},{tags} {','.join(fields)}"
                    lines.append(line)
                    
            except Exception as e:
                print(f"Error processing GPU {gpuId}: {e}")
                
        # send batch data
        if lines:
            if vm_connected:
                send_data_to_vm(lines)
            else:
                print("Not connected to VM")
                
    except Exception as e:
        print(f"Error in DcgmReaderDictionary: {e}")

def getIp():
    client = docker.from_env()
    # List all running containers
    containers = client.containers.list()
    prefix = "dcgm-daemon"
    for container in containers:
        # container.name typically returns something like "dcgm-daemon.<nomad_alloc>" 
        if container.name.startswith(prefix):
            ip = container.attrs["NetworkSettings"]["Networks"]["bridge"]["IPAddress"]
            print(f"Found container '{container.name}' with IP: {ip}")
            return ip
    print(f"No container found with prefix '{prefix}'")
    return None

# get client id!!! Passed in via the hcl jobspec

def getClientId():
    parser = argparse.ArgumentParser(description="DCGM Reader to DB with Nomad client id")
    parser.add_argument("--nomadClientId", required=True, help="Nomad client ID")
    args = parser.parse_args()
    
    nomadClientId = args.nomadClientId
    return nomadClientId


def main(): 
    print('Quokking...')
    hn = getIp()
    print(hn)
    hostname = hn + ":5555"
    print(hostname)

    clientId = getClientId()
    print("Nomad Client ID: ", clientId)
    try:
        while True:
            DcgmReaderDictionary(hostname=hostname, 
                                 field_ids=fieldsToGrab, 
                                 update_frequency=1000000, 
                                 keep_time=3600.0, 
                                 ignores=[], 
                                 field_groups='dcgm_fieldgroupdata')
            time.sleep(1)
    except KeyboardInterrupt:
        print('quokked!')
    

if __name__ == '__main__':
    main()