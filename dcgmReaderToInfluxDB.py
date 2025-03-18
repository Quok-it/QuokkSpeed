# RUN USING: python3 dcgmReaderToDB.py

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
from dotenv import load_dotenv
load_dotenv()

# sending telemetry to InfluxDB database
import influxdb_client
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime

# connect to InfluxDB database
token = "2BKxtdkc6t7G4iUkA6-Iv197sWrA3-sgD-Sp2lk2MUYlGEfDEbXzdJSspLs78toI4vuOrRzBYg0s35s6YoQPLw==" # TODO: how do we not expose this token??
org = "quok"
bucket="db-gpu-polling"

url = "https://mgxvbj8is7-f3zujj6c2wjkpb.timestream-influxdb.us-east-1.on.aws:8086"

# try to connect to InfluxDB client
try:
    write_client = influxdb_client.InfluxDBClient(
        url=url, 
        token=token, 
        org=org,
        timeout=30_000  # 30 sec timeout
    )
    
    # test connection
    print("Testing InfluxDB connection...")
    health = write_client.health()
    print(f"InfluxDB health status: {health.status}")
    
    # set up write API
    write_api = write_client.write_api(write_options=SYNCHRONOUS)
    
except Exception as e:
    print(f"Error connecting to InfluxDB: {str(e)}")
    write_client = None
    write_api = None

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

# try to reconnect to InfluxDB if lost connection / didn't connect
def reconnect_influxdb():
    global write_client, write_api
    
    try:
        print("Attempting to reconnect to InfluxDB...")
        write_client = influxdb_client.InfluxDBClient(
            url=url, 
            token=token, 
            org=org,
            timeout=30_000
        )
        write_api = write_client.write_api(write_options=SYNCHRONOUS)
        health = write_client.health()
        print(f"Reconnection status: {health.status}")
        return True
    except Exception as e:
        print(f"Reconnection failed: {e}")
        return False
class FieldHandlerReader(DcgmReader):
    '''
        Override just this method to do something different per field. 
        This method is called once for each field for each GPU each 
        time that its Process() method is invoked, and it will be skipped
        for blank values and fields in the ignore list.
    '''
    def CustomFieldHandler(self, gpuId, fieldId, fieldTag, val):
        curr_dict[gpuId] = val.value
        print('GPU %d %s(%d) = %s' % (gpuId, fieldTag, fieldId, val.value))

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
    global write_client, write_api
    
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
        
        for gpuId, gpuData in data.items():
            gpu_uuid = gpuData.get("uuid", None)
            # print("gpu_uuid: ", gpu_uuid)
            if gpu_uuid is None:
                # UUID is missing --> error
                print(f"UUID is missing for GPU {gpuId}")
                continue
            
            try:
                clientId = getClientId()
                
                # prep GPU data entry                
                point = Point(gpu_uuid).tag("clientId", clientId)
                
                # store all metrics inside 'fields'
                for fieldName, latest_value, in gpuData.items():
                    # print(fieldName + " : " + latest_value)
                    if latest_value not in [None, "", "N/A"]: 
                        try:
                            # try to convert numerical strings to accepted type
                            if isinstance(latest_value, str):
                                if latest_value.replace('.', '', 1).isdigit():
                                    if '.' in latest_value:
                                        latest_value = float(latest_value)
                                    else:
                                        latest_value = int(latest_value)
                            # add field to point
                            point.field(fieldName, latest_value)
                        except (ValueError, TypeError):
                            # otherwise, keep as string (should all be nums though)
                            point.field(fieldName, str(latest_value))

                # Compute FB_UTIL (Framebuffer Utilization)
                fb_used = gpuData.get("fb_used")
                fb_total = gpuData.get("fb_total")
                # print(f"fb_used: ", fb_used)
                # print(f"fb_total: ", fb_total)
                # print("clientId: " + str(clientId))

                # print(f"fb_util Calculated: ", (100 * round(fb_used / fb_total, 2)))
                if fb_used is not None and fb_total not in [None, 0]:  # Avoid division by zero
                    fb_used = float(fb_used) if isinstance(fb_used, str) else fb_used
                    fb_total = float(fb_total) if isinstance(fb_total, str) else fb_total
                    
                    fb_util = 100 * (fb_used / fb_total)
                    point.field("fb_util", round(fb_util, 2)) # Store as percentage (rounded)
                    
                # set timestamp
                point.time(datetime.now())
                    
                # write to influx
                if write_api:
                    try:
                        write_api.write(bucket=bucket, org=org, record=point)
                        print(f"Data inserted for GPU: {gpu_uuid}")
                    except Exception as e:
                        print(f"Error writing to InfluxDB: {e}")
                        # try to reconnect
                        if reconnect_influxdb():
                            # try writing again after reconnection
                            try:
                                write_api.write(bucket=bucket, org=org, record=point)
                                print(f"Data inserted after reconnection for GPU: {gpu_uuid}")
                            except Exception as e2:
                                print(f"Still failed after reconnection: {e2}")
                else:
                    print("InfluxDB client not initialized, attempting to reconnect...")
                    reconnect_influxdb()
                    
            except Exception as e:
                print(f"Error processing GPU {gpuId}: {e}")
                
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